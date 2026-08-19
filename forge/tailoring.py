"""End-to-end AI plan -> validated JSON -> deterministic DOCX workflow."""

import os
import re
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from .bindings import resolve_bindings
from .context_selection import (
    DEFAULT_CONTEXT_SELECTION_MODEL,
    ContextSelection,
    select_context_with_openai,
)
from .context_store import SQLiteContextStore, read_context_source, sync_context_database
from .docx import RenderReport, render_docx
from .errors import TailoringError
from .jsonio import load_json, write_json
from .job_source import (
    DEFAULT_WEB_SEARCH_MODEL,
    WebJobDescription,
    retrieve_job_description_with_openai,
)
from .keyword_alignment import (
    KeywordAlignment,
    align_job_keywords,
    remove_noop_operations,
)
from .openai_provider import (
    DEFAULT_OPENAI_MODEL,
    build_editable_targets,
    generate_tailoring_plan,
)
from .operations import apply_operations
from .usage_store import OpenAIUsageStore
from .validation import validate_resume

PathLike = Union[str, Path]


@dataclass(frozen=True)
class TailoringResult:
    job_title: str
    company: Optional[str]
    model: str
    context_selection_model: Optional[str]
    web_search_model: Optional[str]
    context_database: Optional[Path]
    workflow_id: str
    usage_database: Path
    usage_summary: Dict[str, Any]
    gaps: Tuple[str, ...]
    job_source_output: Optional[Path]
    context_selection_output: Optional[Path]
    keyword_alignment_output: Optional[Path]
    keyword_coverage: Optional[Dict[str, Any]]
    no_op_operations_removed: Tuple[str, ...]
    operations_output: Path
    data_output: Path
    docx_output: Path
    applied_operations: int
    render_report: RenderReport


def _read_text(path: PathLike, label: str) -> str:
    source = Path(path)
    try:
        value = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise TailoringError(f"Could not read {label} {source}: {exc}") from exc
    if not value.strip():
        raise TailoringError(f"{label.capitalize()} is empty: {source}")
    return value


def safe_filename_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", normalized)
    if not words:
        raise TailoringError(f"Cannot derive a safe filename from {value!r}")
    return "_".join(words)


def tailor_resume_with_openai(
    *,
    template: PathLike,
    data: PathLike,
    schema: PathLike,
    bindings: PathLike,
    job_description: Optional[PathLike] = None,
    job_description_url: Optional[str] = None,
    output_dir: PathLike,
    candidate_prefix: str = "Amin_Haiqal_Resume",
    candidate_context: Optional[PathLike] = None,
    context_database: Optional[PathLike] = None,
    usage_database: Optional[PathLike] = None,
    model: str = DEFAULT_OPENAI_MODEL,
    context_selection_model: str = DEFAULT_CONTEXT_SELECTION_MODEL,
    web_search_model: str = DEFAULT_WEB_SEARCH_MODEL,
    client=None,
) -> TailoringResult:
    """Generate a scoped OpenAI plan, validate it, and render final artifacts."""
    resume = load_json(data)
    resume_schema = load_json(schema)
    binding_config = load_json(bindings)
    validate_resume(resume, resume_schema)

    has_file_jd = job_description is not None
    has_url_jd = isinstance(job_description_url, str) and bool(job_description_url.strip())
    if has_file_jd == has_url_jd:
        raise TailoringError("Supply exactly one of job_description or job_description_url")

    context_text = ""
    context_selection: Optional[ContextSelection] = None
    keyword_alignment: Optional[KeywordAlignment] = None
    web_job: Optional[WebJobDescription] = None
    context_database_path = Path(context_database) if context_database is not None else None
    usage_database_path = (
        Path(usage_database)
        if usage_database is not None
        else context_database_path or Path("data/context.sqlite3")
    )
    usage_store = OpenAIUsageStore(usage_database_path)
    usage_store.initialize()
    workflow_id = str(uuid.uuid4())
    if has_url_jd:
        web_job = retrieve_job_description_with_openai(
            url=job_description_url or "",
            model=web_search_model,
            client=client,
            usage_store=usage_store,
            workflow_id=workflow_id,
        )
        jd_text = web_job.as_tailoring_text()
    else:
        jd_text = _read_text(job_description, "job description")

    if candidate_context is not None:
        if context_database_path is not None:
            sync_context_database(candidate_context, context_database_path)
            chunks = SQLiteContextStore(context_database_path).load_chunks()
        else:
            _, chunks = read_context_source(candidate_context)
    elif context_database_path is not None:
        chunks = SQLiteContextStore(context_database_path).load_chunks()
    else:
        chunks = []

    if chunks:
        context_selection = select_context_with_openai(
            job_description=jd_text,
            chunks=chunks,
            model=context_selection_model,
            client=client,
            usage_store=usage_store,
            workflow_id=workflow_id,
        )
        context_text = context_selection.selected_context_text()
        keyword_alignment = align_job_keywords(
            resume=resume,
            keywords=context_selection.job_keywords,
            selected_chunks=context_selection.selected_chunks,
        )

    plan = generate_tailoring_plan(
        resume=resume,
        job_description=jd_text,
        candidate_context=context_text,
        context_selection=(
            context_selection.as_prompt_summary() if context_selection is not None else None
        ),
        keyword_alignment=(
            keyword_alignment.as_prompt_dict() if keyword_alignment is not None else None
        ),
        model=model,
        client=client,
        usage_store=usage_store,
        workflow_id=workflow_id,
    )
    operation_config = plan.as_operations_config()
    filtered_operations, no_op_targets = remove_noop_operations(
        plan.operations,
        build_editable_targets(resume),
    )
    if not filtered_operations:
        raise TailoringError("OpenAI tailoring plan contained only no-op rewrites")
    operation_config["operations"] = [dict(item) for item in filtered_operations]
    operation_config["provider"]["workflowId"] = workflow_id
    operation_config["provider"]["usageDatabase"] = str(usage_database_path)
    if web_job is not None:
        operation_config["jobSource"] = {
            "type": "url",
            "requestedUrl": web_job.requested_url,
            "model": web_job.model,
            "responseId": web_job.response_id,
        }
    if context_selection is not None:
        operation_config["contextSelection"] = {
            "model": context_selection.model,
            "responseId": context_selection.response_id,
            "database": (
                str(context_database_path) if context_database_path is not None else None
            ),
            "selectedChunkIds": [
                chunk.chunk_id for chunk in context_selection.selected_chunks
            ],
        }
    if keyword_alignment is not None:
        operation_config["keywordAlignment"] = {
            "mode": "balanced",
            "mustSurface": [
                match.keyword.phrase for match in keyword_alignment.must_surface
            ],
            "noOpOperationsRemoved": list(no_op_targets),
        }
    tailored, targets = apply_operations(resume, operation_config)
    validate_resume(tailored, resume_schema)
    before_values = resolve_bindings(resume, binding_config)
    values = resolve_bindings(tailored, binding_config)
    keyword_audit = (
        keyword_alignment.build_audit(
            before_values=before_values,
            after_values=values,
            no_op_targets=no_op_targets,
        )
        if keyword_alignment is not None
        else None
    )
    if keyword_audit is not None and context_selection is not None:
        keyword_audit["provider"] = {
            "workflowId": workflow_id,
            "contextSelectionModel": context_selection.model,
            "contextSelectionResponseId": context_selection.response_id,
            "usageDatabase": str(usage_database_path),
        }

    prefix = safe_filename_component(candidate_prefix)
    title = safe_filename_component(plan.job_title)
    base_name = f"{prefix}_{title}"
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    final_operations = destination / f"{base_name}.operations.json"
    final_job_source = (
        destination / f"{base_name}.job-source.json" if web_job is not None else None
    )
    final_context_selection = (
        destination / f"{base_name}.context-selection.json"
        if context_selection is not None
        else None
    )
    final_keyword_alignment = (
        destination / f"{base_name}.keyword-alignment.json"
        if keyword_audit is not None
        else None
    )
    final_data = destination / f"{base_name}.json"
    final_docx = destination / f"{base_name}.docx"

    try:
        with tempfile.TemporaryDirectory(dir=str(destination), prefix=".forge-tailor-") as temp_dir:
            staging = Path(temp_dir)
            staged_job_source = None
            if web_job is not None and final_job_source is not None:
                staged_job_source = write_json(
                    staging / final_job_source.name,
                    web_job.as_audit_dict(
                        workflow_id=workflow_id,
                        usage_database=str(usage_database_path),
                    ),
                )
            staged_context_selection = None
            if context_selection is not None and final_context_selection is not None:
                selection_audit = context_selection.as_audit_dict()
                selection_audit["provider"]["workflowId"] = workflow_id
                selection_audit["provider"]["usageDatabase"] = str(usage_database_path)
                selection_audit["contextDatabase"] = (
                    str(context_database_path) if context_database_path is not None else None
                )
                staged_context_selection = write_json(
                    staging / final_context_selection.name,
                    selection_audit,
                )
            staged_keyword_alignment = None
            if keyword_audit is not None and final_keyword_alignment is not None:
                staged_keyword_alignment = write_json(
                    staging / final_keyword_alignment.name,
                    keyword_audit,
                )
            staged_operations = write_json(staging / final_operations.name, operation_config)
            staged_data = write_json(staging / final_data.name, tailored)
            staged_docx = staging / final_docx.name
            render_report = render_docx(template, staged_docx, values, strict=True)

            if staged_job_source is not None and final_job_source is not None:
                os.replace(staged_job_source, final_job_source)
            if staged_context_selection is not None and final_context_selection is not None:
                os.replace(staged_context_selection, final_context_selection)
            if staged_keyword_alignment is not None and final_keyword_alignment is not None:
                os.replace(staged_keyword_alignment, final_keyword_alignment)
            os.replace(staged_operations, final_operations)
            os.replace(staged_data, final_data)
            os.replace(staged_docx, final_docx)
    except OSError as exc:
        raise TailoringError(f"Could not publish tailored resume artifacts: {exc}") from exc

    published_report = RenderReport(
        output=final_docx,
        controls=render_report.controls,
        changed_controls=render_report.changed_controls,
        unchanged_controls=render_report.unchanged_controls,
        changed_parts=render_report.changed_parts,
        unused_values=render_report.unused_values,
    )
    usage_summary = usage_store.summary(workflow_id=workflow_id)
    return TailoringResult(
        job_title=plan.job_title,
        company=plan.company,
        model=plan.model,
        context_selection_model=(
            context_selection.model if context_selection is not None else None
        ),
        web_search_model=(web_job.model if web_job is not None else None),
        context_database=context_database_path,
        workflow_id=workflow_id,
        usage_database=usage_database_path,
        usage_summary=usage_summary,
        gaps=plan.gaps,
        job_source_output=final_job_source,
        context_selection_output=final_context_selection,
        keyword_alignment_output=final_keyword_alignment,
        keyword_coverage=(
            keyword_audit.get("coverage") if keyword_audit is not None else None
        ),
        no_op_operations_removed=no_op_targets,
        operations_output=final_operations,
        data_output=final_data,
        docx_output=final_docx,
        applied_operations=len(targets),
        render_report=published_report,
    )
