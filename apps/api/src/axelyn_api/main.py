"""FastAPI application factory and production entry point."""

import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Annotated, AsyncIterator, Callable, Optional

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from forge.errors import ProviderError
from forge.interview_brief import InterviewBriefInputError, generate_interview_brief

from . import __version__
from .auth import ClerkAuthenticator, UserAuthenticator
from .catalog import SERVICE_IDS, SERVICES
from .config import Settings
from .converter import (
    DocumentConversionError,
    DocumentConverter,
    create_document_converter,
)
from .forge_ai import generate_forge_ai_response
from .job_match import (
    IMAGE_SUFFIXES,
    JOB_FILE_SUFFIXES,
    analyze_job_match,
    combine_job_description,
    draft_to_evidence_text,
    extract_job_document,
    tailor_resume_draft,
)
from .models import (
    ForgeAIEnhancementResult,
    ForgeAIMessage,
    ForgeAIMessageCreate,
    ForgeAIMemory,
    ForgeAIThreadCreate,
    ForgeAIThreadDetail,
    ForgeAIThreadSummary,
    HealthResponse,
    AuthenticatedUser,
    GeneratedDocumentBundle,
    GeneratedDocumentSummary,
    InterviewBrief,
    InterviewBriefRequest,
    JobApplicationCreate,
    JobApplicationSummary,
    JobApplicationUpdate,
    JobMatchAnalysis,
    JobMatchDetail,
    JobMatchDocumentBundle,
    JobMatchDocumentSummary,
    JobMatchResult,
    JobMatchSummary,
    ResumeAcceptRequest,
    ResumeDraft,
    ResumeDraftUpdate,
    ResumeImportItem,
    ResumeImportResponse,
    ResumeSourceArtifactSummary,
    ResumeSourceDetail,
    ResumeSourceSummary,
    ResumeTemplateSummary,
    ResumeVariantSummary,
    Service,
    ServiceRequestAccepted,
    ServiceRequestCreate,
)
from .resume_artifacts import (
    JSON_MEDIA_TYPE,
    JSON_SCHEMA_MEDIA_TYPE,
    build_resume_package,
    build_resume_schema,
)
from .resume_assistant import structure_resume_with_openrouter
from .resume_import import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    ResumeImportError,
    decode_json,
    draft_payload,
    encode_json,
    extract_resume,
    normalize_resume_text,
    resume_plain_text,
    unmapped_resume_content,
)
from .resume_enhancer import (
    ResumeEnhancementUnavailable,
    generate_resume_enhancement,
)
from .resume_store import ResumeStore
from .resume_templates import render_resume, template_catalog
from .storage import create_object_store
from .store import ServiceRequestStore
from .website_context import extract_public_urls, retrieve_website_context


PROFILE_PHOTO_MAX_BYTES = 5 * 1024 * 1024
PROFILE_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
PROFILE_PHOTO_METADATA = (
    "profile_photo_filename",
    "profile_photo_media_type",
    "profile_photo_object_key",
)
FORM_RESUME_MEDIA_TYPE = "application/vnd.axelyn.resume+json"
USER_SOURCE_ARTIFACT_KINDS = frozenset({"resume_docx", "resume_pdf"})


def _source_summary(row: dict[str, object]) -> ResumeSourceSummary:
    return ResumeSourceSummary(**row)


def _variant_summary(row: dict[str, object]) -> ResumeVariantSummary:
    return ResumeVariantSummary(**row)


def _document_summary(row: dict[str, object]) -> GeneratedDocumentSummary:
    return GeneratedDocumentSummary(**row)


def _source_artifact_summary(row: dict[str, object]) -> ResumeSourceArtifactSummary:
    return ResumeSourceArtifactSummary(**row)


def _job_document_summary(row: dict[str, object]) -> JobMatchDocumentSummary:
    return JobMatchDocumentSummary(**row)


def _job_match_label(match_state: object) -> str:
    return {
        "match": "Match",
        "some_match": "Some match",
        "no_match": "No match",
    }[str(match_state)]


def _job_application_summary(row: dict[str, object]) -> JobApplicationSummary:
    return JobApplicationSummary(**row)


def _source_detail(
    row: dict[str, object], draft: dict[str, object]
) -> ResumeSourceDetail:
    return ResumeSourceDetail(
        **row,
        draft=ResumeDraft(**draft),
        unmapped_content=unmapped_resume_content(draft),
    )


def _safe_filename(value: str, fallback: str) -> str:
    filename = Path(value).name.strip()[:180]
    return filename or fallback


def _object_prefix(user_id: str) -> str:
    owner_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]
    return f"users/{owner_hash}"


def _profile_photo_payload(upload: UploadFile) -> tuple[bytes, str, str]:
    media_type = (upload.content_type or "").split(";", 1)[0].strip().casefold()
    extension = PROFILE_PHOTO_TYPES.get(media_type)
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Profile photos must be JPEG, PNG, or WebP images.",
        )
    payload = upload.file.read(PROFILE_PHOTO_MAX_BYTES + 1)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose a non-empty profile photo.",
        )
    if len(payload) > PROFILE_PHOTO_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Profile photos are limited to 5 MB.",
        )
    signatures = {
        "image/jpeg": (
            len(payload) >= 4
            and payload.startswith(b"\xff\xd8\xff")
            and payload.endswith(b"\xff\xd9")
        ),
        "image/png": (
            len(payload) >= 24
            and payload.startswith(b"\x89PNG\r\n\x1a\n")
            and payload[12:16] == b"IHDR"
            and int.from_bytes(payload[16:20], "big") > 0
            and int.from_bytes(payload[20:24], "big") > 0
        ),
        "image/webp": (
            len(payload) >= 20
            and payload.startswith(b"RIFF")
            and payload[8:12] == b"WEBP"
            and payload[12:16] in {b"VP8 ", b"VP8L", b"VP8X"}
            and int.from_bytes(payload[4:8], "little") + 8 <= len(payload)
        ),
    }
    if not signatures[media_type]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The selected file does not match its image format.",
        )
    return payload, media_type, extension


def _preserve_profile_photo(
    draft: dict[str, object], original: dict[str, object]
) -> None:
    for key in PROFILE_PHOTO_METADATA:
        value = original.get(key)
        if value:
            draft[key] = value


def _editable_draft(payload: ResumeDraftUpdate) -> dict[str, object]:
    sections = payload.sections
    experience_entries = [
        entry.model_dump() for entry in payload.experience_entries
    ]
    education_entries = [
        entry.model_dump() for entry in payload.education_entries
    ]
    project_entries = [
        entry.model_dump() for entry in payload.project_entries
    ]
    skill_categories = [
        category.model_dump() for category in payload.skill_categories
    ]
    custom_sections = [section.model_dump() for section in payload.custom_sections]
    if not sections and "sections" not in payload.model_fields_set:
        normalized = normalize_resume_text(payload.extracted_text)
        sections = normalized.get("sections", {})
        if not custom_sections and "custom_sections" not in payload.model_fields_set:
            custom_sections = list(normalized.get("custom_sections", []))
    return {
        "display_name": payload.display_name,
        "target_role": payload.target_role,
        "template_id": payload.template_id,
        "full_name": payload.full_name,
        "headline": payload.headline,
        "email_address": payload.email_address,
        "phone_number": payload.phone_number,
        "location": payload.location,
        "linkedin_url": payload.linkedin_url,
        "portfolio_url": payload.portfolio_url,
        "github_url": payload.github_url,
        "other_professional_link": payload.other_professional_link,
        "contact_line": payload.contact_line,
        "summary": payload.summary,
        "extracted_text": payload.extracted_text,
        "sections": sections,
        "experience_entries": experience_entries,
        "education_entries": education_entries,
        "project_entries": project_entries,
        "skill_categories": skill_categories,
        "custom_sections": custom_sections,
    }


def _render_resume_docx(
    *,
    draft: dict[str, object],
    title: str,
    description: str,
    content_controls: bool = False,
) -> tuple[bytes, str, str]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        output = Path(temporary_directory) / "resume.docx"
        template_id, template_version = render_resume(
            draft=draft,
            output=output,
            title=title,
            description=description,
            content_controls=content_controls,
        )
        return output.read_bytes(), template_id, template_version


def _source_artifact_payloads(
    *,
    prefix: str,
    normalized_docx: bytes,
    draft: dict[str, object],
    display_name: str,
    target_role: str | None,
    original_filename: str,
    document_converter: DocumentConverter,
) -> list[dict[str, object]]:
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", display_name).strip("-.")
    safe_stem = safe_stem or "resume"
    standard_docx, _, _ = _render_resume_docx(
        draft=draft,
        title=display_name,
        description="Axelyn standard resume generated from a normalized Word source.",
        content_controls=True,
    )
    finished_filename = f"{safe_stem}.docx"
    finished_pdf = document_converter.docx_to_pdf(
        standard_docx,
        finished_filename,
    )
    resume_json = build_resume_package(
        draft=draft,
        display_name=display_name,
        target_role=target_role,
        original_filename=original_filename,
    )
    resume_schema = build_resume_schema()
    artifacts = (
        (
            "source_docx",
            f"{safe_stem}-source.docx",
            DOCX_MEDIA_TYPE,
            normalized_docx,
            "source.docx",
        ),
        (
            "resume_docx",
            finished_filename,
            DOCX_MEDIA_TYPE,
            standard_docx,
            "resume.docx",
        ),
        (
            "resume_pdf",
            f"{safe_stem}.pdf",
            PDF_MEDIA_TYPE,
            finished_pdf,
            "resume.pdf",
        ),
        (
            "resume_json",
            f"{safe_stem}.json",
            JSON_MEDIA_TYPE,
            resume_json,
            "resume.json",
        ),
        (
            "resume_schema",
            f"{safe_stem}.schema.json",
            JSON_SCHEMA_MEDIA_TYPE,
            resume_schema,
            "resume.schema.json",
        ),
    )
    return [
        {
            "kind": kind,
            "filename": filename,
            "media_type": media_type,
            "payload": payload,
            "byte_size": len(payload),
            "object_key": f"{prefix}/artifacts/{object_name}",
        }
        for kind, filename, media_type, payload, object_name in artifacts
    ]


def create_app(
    settings: Optional[Settings] = None,
    authenticate_user: Optional[UserAuthenticator] = None,
    document_converter: Optional[DocumentConverter] = None,
    interview_brief_generator: Optional[Callable[..., dict[str, Any]]] = None,
    resume_draft_generator: Optional[Callable[..., dict[str, object]]] = None,
    forge_ai_generator: Optional[Callable[..., dict[str, object]]] = None,
    resume_enhancement_generator: Optional[Callable[..., dict[str, object]]] = None,
    website_context_reader: Optional[Callable[..., object]] = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environ()
    store = ServiceRequestStore(resolved_settings.database_path)
    resume_store = ResumeStore(resolved_settings.database_path)
    object_store = create_object_store(
        storage_path=resolved_settings.storage_path,
        endpoint=resolved_settings.storage_endpoint,
        token=resolved_settings.storage_token,
    )
    user_authenticator = authenticate_user or ClerkAuthenticator(resolved_settings)
    converter = document_converter or create_document_converter(
        resolved_settings.converter_endpoint,
        resolved_settings.converter_timeout_seconds,
    )
    brief_generator = interview_brief_generator or generate_interview_brief
    coach_generator = forge_ai_generator or generate_forge_ai_response
    enhancement_generator = (
        resume_enhancement_generator or generate_resume_enhancement
    )
    website_reader = website_context_reader or retrieve_website_context
    draft_generator = resume_draft_generator
    if draft_generator is None and resolved_settings.environment.casefold() != "test":
        draft_generator = structure_resume_with_openrouter

    def require_user(request: Request) -> str:
        return user_authenticator(request)

    def require_editable_source(row: dict[str, object]) -> None:
        if str(row["media_type"]) != FORM_RESUME_MEDIA_TYPE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Imported resumes cannot be edited. Delete this resume and "
                    "upload a replacement file."
                ),
            )

    def forge_ai_message(row: dict[str, object]) -> ForgeAIMessage:
        try:
            citations = json.loads(str(row["citations_json"]))
        except (json.JSONDecodeError, TypeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Forge AI message data is temporarily unavailable.",
            ) from error
        return ForgeAIMessage(**row, citations=citations)

    def forge_ai_context(
        user_id: str,
        thread: dict[str, object],
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        str,
        JobMatchAnalysis,
        ForgeAIMemory,
        JobMatchAnalysis,
    ]:
        match = resume_store.get_job_match(user_id, str(thread["match_id"]))
        source = resume_store.get_source(user_id, str(thread["source_id"]))
        if match is None or source is None:
            raise HTTPException(status_code=404, detail="Forge AI workspace not found.")
        try:
            resume = decode_json(
                object_store.get(str(match["resume_snapshot_object_key"]))
            )
            job_description = object_store.get(
                str(match["job_description_object_key"])
            ).decode("utf-8")
            saved_analysis = JobMatchAnalysis(
                **decode_json(object_store.get(str(match["analysis_object_key"])))
            )
            memory = ForgeAIMemory(**json.loads(str(thread["memory_json"])))
        except (KeyError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Forge AI context is temporarily unavailable.",
            ) from error
        user_facts = "\n".join(
            fact.fact for fact in memory.confirmed_facts if fact.source == "user"
        )
        evidence_text = draft_to_evidence_text(resume)
        if user_facts:
            evidence_text = f"{evidence_text}\n{user_facts}"
        current_analysis = analyze_job_match(
            target_role=str(match["target_role"]),
            company=str(match["company"]) if match["company"] else None,
            job_description=job_description,
            resume_text=evidence_text,
        )
        return (
            match,
            source,
            resume,
            job_description,
            saved_analysis,
            memory,
            current_analysis,
        )

    def forge_ai_thread_detail(
        user_id: str,
        thread: dict[str, object],
    ) -> ForgeAIThreadDetail:
        match, source, _, _, _, memory, analysis = forge_ai_context(user_id, thread)
        message_rows = resume_store.list_forge_ai_messages(user_id, str(thread["id"]))
        return ForgeAIThreadDetail(
            **thread,
            target_role=str(match["target_role"]),
            company=str(match["company"]) if match["company"] else None,
            resume_name=str(source["display_name"]),
            message_count=len(message_rows),
            match_state=analysis.match_state,
            match_label=analysis.match_label,
            missing_keywords=analysis.missing_keywords,
            matched_keywords=analysis.matched_keywords,
            memory=memory,
            messages=[forge_ai_message(row) for row in message_rows],
            documents=[
                _job_document_summary(row)
                for row in resume_store.list_job_match_documents(
                    user_id, str(thread["match_id"])
                )
            ],
        )

    def resolve_application_resume(
        user_id: str,
        source_id: str,
        variant_id: str | None,
    ) -> tuple[dict[str, object], dict[str, object] | None]:
        source = resume_store.get_source(user_id, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Resume source not found.")
        variant: dict[str, object] | None = None
        if variant_id is not None:
            variant = resume_store.get_variant(user_id, variant_id)
            if variant is None or str(variant["source_id"]) != source_id:
                raise HTTPException(
                    status_code=404,
                    detail="Resume version not found for this source.",
                )
        return source, variant

    def application_resume_snapshot(
        source: dict[str, object],
        variant: dict[str, object] | None,
    ) -> bytes:
        object_key = (
            variant["normalized_object_key"]
            if variant is not None
            else source["draft_object_key"]
        )
        try:
            return object_store.get(str(object_key))
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The selected resume data is temporarily unavailable.",
            ) from error

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        resume_store.initialize()
        yield

    app = FastAPI(
        title="Axelyn Forge API",
        summary="Service intake and private resume workflows for Axelyn Forge.",
        version=__version__,
        docs_url=(
            None
            if resolved_settings.environment.casefold() == "production"
            else "/api/docs"
        ),
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.service_request_store = store
    app.state.resume_store = resume_store
    app.state.object_store = object_store
    app.state.document_converter = converter
    app.state.interview_brief_generator = brief_generator
    app.state.resume_draft_generator = draft_generator
    app.state.forge_ai_generator = coach_generator
    app.state.resume_enhancement_generator = enhancement_generator
    app.state.website_context_reader = website_reader

    if resolved_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.get("/healthz", include_in_schema=False)
    @app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
    def health(request: Request) -> HealthResponse:
        request.app.state.service_request_store.ping()
        return HealthResponse(
            status="ok",
            service="axelyn-forge-api",
            version=__version__,
        )

    @app.get("/api/v1/services", response_model=list[Service], tags=["services"])
    def list_services() -> list[Service]:
        return [Service(**service) for service in SERVICES]

    @app.get("/api/v1/me", response_model=AuthenticatedUser, tags=["account"])
    def current_user(
        user_id: Annotated[str, Depends(require_user)],
    ) -> AuthenticatedUser:
        return AuthenticatedUser(user_id=user_id)

    @app.post(
        "/api/v1/service-requests",
        response_model=ServiceRequestAccepted,
        status_code=status.HTTP_201_CREATED,
        tags=["services"],
    )
    def create_service_request(
        payload: ServiceRequestCreate,
        request: Request,
    ) -> ServiceRequestAccepted:
        if payload.service_id not in SERVICE_IDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unknown service_id. Choose a service returned by /api/v1/services.",
            )
        return request.app.state.service_request_store.create(payload)

    @app.get(
        "/api/v1/resumes",
        response_model=list[ResumeSourceSummary],
        tags=["resumes"],
    )
    def list_resumes(
        request: Request,
        user_id: Annotated[str, Depends(require_user)],
    ) -> list[ResumeSourceSummary]:
        rows = request.app.state.resume_store.list_sources(user_id)
        return [_source_summary(row) for row in rows]

    @app.get(
        "/api/v1/resume-source-artifacts",
        response_model=list[ResumeSourceArtifactSummary],
        tags=["resumes"],
    )
    def list_resume_source_artifacts(
        user_id: Annotated[str, Depends(require_user)],
    ) -> list[ResumeSourceArtifactSummary]:
        return [
            _source_artifact_summary(row)
            for row in resume_store.list_source_artifacts(user_id)
            if str(row["kind"]) in USER_SOURCE_ARTIFACT_KINDS
        ]

    @app.get(
        "/api/v1/resume-source-artifacts/{artifact_id}/download",
        tags=["resumes"],
    )
    def download_resume_source_artifact(
        artifact_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> Response:
        artifact = resume_store.get_source_artifact(user_id, artifact_id)
        if artifact is None or str(artifact["kind"]) not in USER_SOURCE_ARTIFACT_KINDS:
            raise HTTPException(status_code=404, detail="Resume artifact not found.")
        try:
            payload = object_store.get(str(artifact["object_key"]))
        except KeyError as error:
            raise HTTPException(
                status_code=503,
                detail="Resume artifact is temporarily unavailable.",
            ) from error
        filename = _safe_filename(str(artifact["filename"]), "resume")
        download_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-.")
        return Response(
            payload,
            media_type=str(artifact["media_type"]),
            headers={
                "Content-Disposition": f'attachment; filename="{download_name or "resume"}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get(
        "/api/v1/resume-templates",
        response_model=list[ResumeTemplateSummary],
        tags=["resumes"],
    )
    def list_resume_templates() -> list[ResumeTemplateSummary]:
        return [ResumeTemplateSummary(**template) for template in template_catalog()]

    @app.post(
        "/api/v1/resumes",
        response_model=ResumeSourceDetail,
        status_code=status.HTTP_201_CREATED,
        tags=["resumes"],
    )
    def create_resume_from_form(
        payload: ResumeDraftUpdate,
        user_id: Annotated[str, Depends(require_user)],
    ) -> ResumeSourceDetail:
        source_id = "src_" + uuid.uuid4().hex
        draft = _editable_draft(payload)
        # A form-created resume has no imported source transcript. The structured
        # fields are canonical, so later edits cannot appear as false unmapped text.
        draft["extracted_text"] = ""
        has_content = bool(resume_plain_text(draft).strip())
        encoded = encode_json(draft)
        prefix = f"{_object_prefix(user_id)}/sources/{source_id}"
        original_key = f"{prefix}/original.forge.json"
        draft_key = f"{prefix}/draft.json"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", payload.display_name).strip("-.")
        original_filename = f"{safe_name or 'resume'}.forge.json"
        stored_keys: list[str] = []
        try:
            object_store.put(
                original_key,
                encoded,
                "application/vnd.axelyn.resume+json",
            )
            stored_keys.append(original_key)
            object_store.put(draft_key, encoded, "application/json")
            stored_keys.append(draft_key)
            row = resume_store.create_source(
                source_id=source_id,
                user_id=user_id,
                display_name=payload.display_name,
                target_role=payload.target_role,
                original_filename=original_filename,
                media_type=FORM_RESUME_MEDIA_TYPE,
                byte_size=len(encoded),
                sha256=hashlib.sha256(encoded).hexdigest(),
                original_object_key=original_key,
                draft_object_key=draft_key,
                status="needs_review" if has_content else "needs_ocr",
                warning=None if has_content else "Content is required.",
            )
        except Exception:
            for key in stored_keys:
                object_store.delete(key)
            raise
        return _source_detail(row, draft)

    @app.post(
        "/api/v1/resumes/imports",
        response_model=ResumeImportResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["resumes"],
    )
    def import_resumes(
        user_id: Annotated[str, Depends(require_user)],
        files: Annotated[list[UploadFile], File()],
        target_role: Annotated[str | None, Form()] = None,
    ) -> ResumeImportResponse:
        if not files or len(files) > resolved_settings.max_resume_files:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Upload between 1 and {resolved_settings.max_resume_files} files.",
            )
        clean_role = target_role.strip()[:160] if target_role else None
        items: list[ResumeImportItem] = []
        owner_prefix = _object_prefix(user_id)
        for upload in files:
            original_name = _safe_filename(upload.filename or "", "resume")
            payload = upload.file.read(resolved_settings.max_resume_bytes + 1)
            if len(payload) > resolved_settings.max_resume_bytes:
                items.append(
                    ResumeImportItem(
                        filename=original_name,
                        status="rejected",
                        error="Files are limited to 10 MB each.",
                    )
                )
                continue
            try:
                extracted = extract_resume(original_name, payload)
            except ResumeImportError as error:
                items.append(
                    ResumeImportItem(
                        filename=original_name,
                        status="rejected",
                        error=str(error),
                    )
                )
                continue

            normalized_docx = payload
            normalized_text = extracted.text
            normalized_warning = extracted.warning
            if extracted.media_type == PDF_MEDIA_TYPE:
                try:
                    normalized_docx = converter.pdf_to_docx(payload, original_name)
                    word_extraction = extract_resume(
                        f"{Path(original_name).stem}.docx",
                        normalized_docx,
                    )
                except (DocumentConversionError, ResumeImportError):
                    items.append(
                        ResumeImportItem(
                            filename=original_name,
                            status="rejected",
                            error=(
                                "LibreOffice could not convert this PDF into an "
                                "editable Word document."
                            ),
                        )
                    )
                    continue
                normalized_text = word_extraction.text
                normalized_warning = word_extraction.warning or extracted.warning

            source_id = "src_" + uuid.uuid4().hex
            suffix = Path(original_name).suffix.casefold()
            stem = Path(original_name).stem.strip()[:160] or "Imported resume"
            prefix = f"{owner_prefix}/sources/{source_id}"
            original_key = f"{prefix}/original{suffix}"
            draft_key = f"{prefix}/draft.json"
            draft = draft_payload(
                extracted_text=normalized_text,
                display_name=stem,
                target_role=clean_role,
            )
            if draft_generator is not None and normalized_text:
                try:
                    generated_draft = draft_generator(
                        extracted_text=normalized_text,
                        display_name=stem,
                        target_role=clean_role,
                    )
                    generated_draft["template_id"] = "ats-classic"
                    generated_draft["extracted_text"] = normalized_text
                    validated_draft = ResumeDraft.model_validate(
                        generated_draft
                    ).model_dump(mode="json")
                    draft = {
                        "display_name": stem,
                        "target_role": clean_role,
                        **validated_draft,
                    }
                except (ProviderError, ValueError):
                    ai_warning = (
                        "AI structuring was temporarily unavailable. Forge used its "
                        "deterministic parser. Review the DOCX and PDF, then delete "
                        "and re-upload the source if changes are needed."
                    )
                    normalized_warning = " ".join(
                        value for value in (normalized_warning, ai_warning) if value
                    )
            if not normalized_text.strip():
                items.append(
                    ResumeImportItem(
                        filename=original_name,
                        status="rejected",
                        error=(
                            "No readable resume text was found. Export a searchable "
                            "PDF or DOCX and upload it again."
                        ),
                    )
                )
                continue
            try:
                artifact_payloads = _source_artifact_payloads(
                    prefix=prefix,
                    normalized_docx=normalized_docx,
                    draft=draft,
                    display_name=stem,
                    target_role=clean_role,
                    original_filename=original_name,
                    document_converter=converter,
                )
            except DocumentConversionError:
                items.append(
                    ResumeImportItem(
                        filename=original_name,
                        status="rejected",
                        error="Forge could not create the finished PDF. Try again.",
                    )
                )
                continue
            stored_keys: list[str] = []
            created_source = False
            try:
                object_store.put(original_key, payload, extracted.media_type)
                stored_keys.append(original_key)
                object_store.put(draft_key, encode_json(draft), "application/json")
                stored_keys.append(draft_key)
                for artifact in artifact_payloads:
                    object_store.put(
                        str(artifact["object_key"]),
                        bytes(artifact["payload"]),
                        str(artifact["media_type"]),
                    )
                    stored_keys.append(str(artifact["object_key"]))
                row = resume_store.create_source(
                    source_id=source_id,
                    user_id=user_id,
                    display_name=stem,
                    target_role=clean_role,
                    original_filename=original_name,
                    media_type=extracted.media_type,
                    byte_size=len(payload),
                    sha256=extracted.checksum,
                    original_object_key=original_key,
                    draft_object_key=draft_key,
                    status="ready",
                    warning=normalized_warning,
                )
                created_source = True
                artifact_rows = resume_store.upsert_source_artifacts(
                    user_id=user_id,
                    source_id=source_id,
                    artifacts=[
                        {key: value for key, value in artifact.items() if key != "payload"}
                        for artifact in artifact_payloads
                    ],
                )
                if artifact_rows is None:
                    raise RuntimeError("Resume artifact metadata could not be stored.")
            except Exception:
                if created_source:
                    resume_store.delete_source(user_id, source_id)
                for key in stored_keys:
                    object_store.delete(key)
                raise
            items.append(
                ResumeImportItem(
                    filename=original_name,
                    status="stored",
                    source=_source_summary(row),
                )
            )
        return ResumeImportResponse(items=items)

    @app.get(
        "/api/v1/resumes/{source_id}",
        response_model=ResumeSourceDetail,
        tags=["resumes"],
    )
    def get_resume(
        source_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> ResumeSourceDetail:
        row = resume_store.get_source(user_id, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        require_editable_source(row)
        try:
            draft = decode_json(object_store.get(str(row["draft_object_key"])))
        except KeyError as error:
            raise HTTPException(status_code=503, detail="Resume draft is unavailable.") from error
        return _source_detail(row, draft)

    @app.put(
        "/api/v1/resumes/{source_id}/profile-photo",
        response_model=ResumeSourceDetail,
        tags=["resumes"],
    )
    def upload_resume_profile_photo(
        source_id: str,
        user_id: Annotated[str, Depends(require_user)],
        photo: Annotated[UploadFile, File()],
    ) -> ResumeSourceDetail:
        row = resume_store.get_source(user_id, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        require_editable_source(row)
        try:
            draft = decode_json(object_store.get(str(row["draft_object_key"])))
        except KeyError as error:
            raise HTTPException(
                status_code=503, detail="Resume draft is unavailable."
            ) from error
        payload, media_type, extension = _profile_photo_payload(photo)
        old_key = str(draft.get("profile_photo_object_key") or "")
        new_key = (
            f"{_object_prefix(user_id)}/sources/{source_id}/profile-photo/"
            f"{uuid.uuid4().hex}{extension}"
        )
        draft["profile_photo_filename"] = _safe_filename(
            photo.filename or "", f"profile-photo{extension}"
        )
        draft["profile_photo_media_type"] = media_type
        draft["profile_photo_object_key"] = new_key
        try:
            object_store.put(new_key, payload, media_type)
            object_store.put(
                str(row["draft_object_key"]), encode_json(draft), "application/json"
            )
        except Exception:
            object_store.delete(new_key)
            raise
        if old_key and old_key != new_key:
            object_store.delete(old_key)
        return _source_detail(row, draft)

    @app.get(
        "/api/v1/resumes/{source_id}/profile-photo",
        tags=["resumes"],
    )
    def get_resume_profile_photo(
        source_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> Response:
        row = resume_store.get_source(user_id, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        try:
            draft = decode_json(object_store.get(str(row["draft_object_key"])))
            object_key = str(draft.get("profile_photo_object_key") or "")
            if not object_key:
                raise KeyError(source_id)
            payload = object_store.get(object_key)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Profile photo not found.") from error
        media_type = str(draft.get("profile_photo_media_type") or "image/jpeg")
        filename = _safe_filename(
            str(draft.get("profile_photo_filename") or ""), "profile-photo"
        )
        download_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-.")
        return Response(
            payload,
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f'inline; filename="{download_name or "profile-photo"}"'
                ),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.delete(
        "/api/v1/resumes/{source_id}/profile-photo",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["resumes"],
    )
    def delete_resume_profile_photo(
        source_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> Response:
        row = resume_store.get_source(user_id, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        require_editable_source(row)
        try:
            draft = decode_json(object_store.get(str(row["draft_object_key"])))
        except KeyError as error:
            raise HTTPException(
                status_code=503, detail="Resume draft is unavailable."
            ) from error
        object_key = str(draft.pop("profile_photo_object_key", "") or "")
        draft.pop("profile_photo_filename", None)
        draft.pop("profile_photo_media_type", None)
        object_store.put(
            str(row["draft_object_key"]), encode_json(draft), "application/json"
        )
        if object_key:
            object_store.delete(object_key)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/resumes/{source_id}/editable.docx",
        tags=["resumes"],
    )
    def download_editable_resume(
        source_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> Response:
        row = resume_store.get_source(user_id, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        require_editable_source(row)
        try:
            draft = decode_json(object_store.get(str(row["draft_object_key"])))
        except KeyError as error:
            raise HTTPException(status_code=503, detail="Resume draft is unavailable.") from error
        if not resume_plain_text(draft).strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Add resume content before creating an editable Word draft.",
            )
        document_payload, _, _ = _render_resume_docx(
            draft=draft,
            title=str(row["display_name"]),
            description="Editable Word draft generated from a private resume source.",
        )
        safe_stem = re.sub(
            r"[^A-Za-z0-9._-]+", "-", str(row["display_name"])
        ).strip("-.")
        filename = f"{safe_stem or 'resume'}-editable.docx"
        return Response(
            document_payload,
            media_type=DOCX_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.put(
        "/api/v1/resumes/{source_id}/draft",
        response_model=ResumeSourceDetail,
        tags=["resumes"],
    )
    def update_resume_draft(
        source_id: str,
        payload: ResumeDraftUpdate,
        user_id: Annotated[str, Depends(require_user)],
    ) -> ResumeSourceDetail:
        row = resume_store.get_source(user_id, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        require_editable_source(row)
        draft = _editable_draft(payload)
        try:
            original_draft = decode_json(
                object_store.get(str(row["draft_object_key"]))
            )
        except KeyError as error:
            raise HTTPException(
                status_code=503,
                detail="Resume draft is unavailable.",
            ) from error
        draft["extracted_text"] = str(original_draft.get("extracted_text") or "")
        _preserve_profile_photo(draft, original_draft)
        has_content = bool(resume_plain_text(draft).strip())
        object_store.put(str(row["draft_object_key"]), encode_json(draft), "application/json")
        updated = resume_store.update_source(
            user_id=user_id,
            source_id=source_id,
            display_name=payload.display_name,
            target_role=payload.target_role,
            draft_object_key=str(row["draft_object_key"]),
            status="needs_review" if has_content else "needs_ocr",
            warning=None if has_content else str(row.get("warning") or "Content is required."),
        )
        assert updated is not None
        return _source_detail(updated, draft)

    @app.post(
        "/api/v1/resumes/{source_id}/accept",
        response_model=ResumeVariantSummary,
        tags=["resumes"],
    )
    def accept_resume(
        source_id: str,
        payload: ResumeAcceptRequest,
        user_id: Annotated[str, Depends(require_user)],
    ) -> ResumeVariantSummary:
        row = resume_store.get_source(user_id, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        require_editable_source(row)
        draft = _editable_draft(payload)
        try:
            original_draft = decode_json(
                object_store.get(str(row["draft_object_key"]))
            )
        except KeyError as error:
            raise HTTPException(
                status_code=503,
                detail="Resume draft is unavailable.",
            ) from error
        draft["extracted_text"] = str(original_draft.get("extracted_text") or "")
        _preserve_profile_photo(draft, original_draft)
        if not resume_plain_text(draft).strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Add resume content before accepting this version.",
            )
        normalized_key = f"{_object_prefix(user_id)}/variants/{source_id}/resume.json"
        object_store.put(normalized_key, encode_json(draft), "application/json")
        object_store.put(str(row["draft_object_key"]), encode_json(draft), "application/json")
        variant = resume_store.accept_source(
            user_id=user_id,
            source_id=source_id,
            name=payload.variant_name,
            target_role=payload.target_role,
            normalized_object_key=normalized_key,
        )
        assert variant is not None
        return _variant_summary(variant)

    @app.delete(
        "/api/v1/resumes/{source_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["resumes"],
    )
    def delete_resume(
        source_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> Response:
        keys = resume_store.source_object_keys(user_id, source_id)
        if keys is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        row = resume_store.get_source(user_id, source_id)
        if row is not None:
            try:
                draft = decode_json(object_store.get(str(row["draft_object_key"])))
                photo_key = str(draft.get("profile_photo_object_key") or "")
                if photo_key:
                    keys.append(photo_key)
            except KeyError:
                pass
        for key in set(keys):
            object_store.delete(key)
        if not resume_store.delete_source(user_id, source_id):
            raise HTTPException(status_code=404, detail="Resume not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/resume-variants",
        response_model=list[ResumeVariantSummary],
        tags=["resumes"],
    )
    def list_resume_variants(
        user_id: Annotated[str, Depends(require_user)],
    ) -> list[ResumeVariantSummary]:
        return [
            _variant_summary(row) for row in resume_store.list_variants(user_id)
        ]

    @app.get(
        "/api/v1/generated-documents",
        response_model=list[GeneratedDocumentSummary],
        tags=["resumes"],
    )
    def list_generated_documents(
        user_id: Annotated[str, Depends(require_user)],
    ) -> list[GeneratedDocumentSummary]:
        return [
            _document_summary(row) for row in resume_store.list_documents(user_id)
        ]

    @app.post(
        "/api/v1/resume-variants/{variant_id}/render",
        response_model=GeneratedDocumentBundle,
        status_code=status.HTTP_201_CREATED,
        tags=["resumes"],
    )
    def render_resume_variant(
        variant_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> GeneratedDocumentBundle:
        variant = resume_store.get_variant(user_id, variant_id)
        if variant is None:
            raise HTTPException(status_code=404, detail="Resume version not found.")
        try:
            normalized = decode_json(
                object_store.get(str(variant["normalized_object_key"]))
            )
        except KeyError as error:
            raise HTTPException(status_code=503, detail="Resume data is unavailable.") from error

        document_payload, template_id, template_version = _render_resume_docx(
            draft=normalized,
            title=str(variant["name"]),
            description="Resume generated from user-approved source material.",
        )

        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", str(variant["name"])).strip("-.")
        base_filename = f"{safe_stem or 'resume'}-axelyn-forge"
        try:
            pdf_payload = converter.docx_to_pdf(
                document_payload,
                f"{base_filename}.docx",
            )
        except DocumentConversionError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The LibreOffice PDF converter is temporarily unavailable.",
            ) from error

        generation_id = uuid.uuid4().hex
        object_prefix = f"{_object_prefix(user_id)}/documents/{variant_id}/{generation_id}"
        artifacts = [
            {
                "filename": f"{base_filename}.docx",
                "media_type": DOCX_MEDIA_TYPE,
                "object_key": f"{object_prefix}.docx",
                "payload": document_payload,
            },
            {
                "filename": f"{base_filename}.pdf",
                "media_type": PDF_MEDIA_TYPE,
                "object_key": f"{object_prefix}.pdf",
                "payload": pdf_payload,
            },
        ]
        stored_keys: list[str] = []
        try:
            for artifact in artifacts:
                object_store.put(
                    str(artifact["object_key"]),
                    bytes(artifact["payload"]),
                    str(artifact["media_type"]),
                )
                stored_keys.append(str(artifact["object_key"]))
            rows = resume_store.create_documents(
                user_id=user_id,
                variant_id=variant_id,
                documents=[
                    {
                        "filename": str(artifact["filename"]),
                        "media_type": str(artifact["media_type"]),
                        "object_key": str(artifact["object_key"]),
                        "template_id": template_id,
                        "template_version": template_version,
                    }
                    for artifact in artifacts
                ],
            )
        except Exception:
            for key in stored_keys:
                object_store.delete(key)
            raise
        assert rows is not None
        return GeneratedDocumentBundle(
            documents=[_document_summary(row) for row in rows]
        )

    @app.get(
        "/api/v1/documents/{document_id}/download",
        tags=["resumes"],
    )
    def download_document(
        document_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> Response:
        document = resume_store.get_document(user_id, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        try:
            payload = object_store.get(str(document["object_key"]))
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Document not found.") from error
        filename = _safe_filename(str(document["filename"]), "resume.docx")
        return Response(
            payload,
            media_type=str(document["media_type"]),
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get(
        "/api/v1/job-applications",
        response_model=list[JobApplicationSummary],
        tags=["job tracker"],
    )
    def list_job_applications(
        user_id: Annotated[str, Depends(require_user)],
    ) -> list[JobApplicationSummary]:
        return [
            _job_application_summary(row)
            for row in resume_store.list_job_applications(user_id)
        ]

    @app.post(
        "/api/v1/job-applications",
        response_model=JobApplicationSummary,
        status_code=status.HTTP_201_CREATED,
        tags=["job tracker"],
    )
    def create_job_application(
        payload: JobApplicationCreate,
        user_id: Annotated[str, Depends(require_user)],
    ) -> JobApplicationSummary:
        source, variant = resolve_application_resume(
            user_id,
            payload.resume_source_id,
            payload.resume_variant_id,
        )
        application_id = "job_" + uuid.uuid4().hex
        snapshot_key = (
            f"{_object_prefix(user_id)}/job-applications/{application_id}/"
            "resume.json"
        )
        object_store.put(
            snapshot_key,
            application_resume_snapshot(source, variant),
            "application/json",
        )
        try:
            row = resume_store.create_job_application(
                application_id=application_id,
                user_id=user_id,
                company_name=payload.company_name,
                job_title=payload.job_title,
                job_url=payload.job_url,
                location=payload.location,
                work_arrangement=payload.work_arrangement,
                employment_type=payload.employment_type,
                status=payload.status,
                applied_on=payload.applied_on,
                next_action_on=payload.next_action_on,
                notes=payload.notes,
                resume_source_id=payload.resume_source_id,
                resume_variant_id=payload.resume_variant_id,
                resume_name=str(
                    variant["name"]
                    if variant is not None
                    else source["display_name"]
                ),
                resume_target_role=(
                    str(variant["target_role"])
                    if variant is not None and variant["target_role"]
                    else str(source["target_role"])
                    if source["target_role"]
                    else None
                ),
                resume_snapshot_object_key=snapshot_key,
            )
        except Exception:
            object_store.delete(snapshot_key)
            raise
        return _job_application_summary(row)

    @app.put(
        "/api/v1/job-applications/{application_id}",
        response_model=JobApplicationSummary,
        tags=["job tracker"],
    )
    def update_job_application(
        application_id: str,
        payload: JobApplicationUpdate,
        user_id: Annotated[str, Depends(require_user)],
    ) -> JobApplicationSummary:
        existing = resume_store.get_job_application(user_id, application_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Job application not found.")

        resume_selection_changed = (
            payload.resume_source_id is not None
            and (
                payload.resume_source_id != existing["resume_source_id"]
                or payload.resume_variant_id != existing["resume_variant_id"]
            )
        )
        source_id = (
            payload.resume_source_id
            if payload.resume_source_id is not None
            else existing["resume_source_id"]
        )
        variant_id = (
            payload.resume_variant_id
            if payload.resume_source_id is not None
            else existing["resume_variant_id"]
        )
        resume_name = str(existing["resume_name"])
        resume_target_role = (
            str(existing["resume_target_role"])
            if existing["resume_target_role"]
            else None
        )
        snapshot_key = str(existing["resume_snapshot_object_key"])
        previous_snapshot_key = snapshot_key
        stored_replacement = False
        if resume_selection_changed:
            source, variant = resolve_application_resume(
                user_id,
                payload.resume_source_id,
                payload.resume_variant_id,
            )
            resume_name = str(
                variant["name"] if variant is not None else source["display_name"]
            )
            resume_target_role = (
                str(variant["target_role"])
                if variant is not None and variant["target_role"]
                else str(source["target_role"])
                if source["target_role"]
                else None
            )
            snapshot_key = (
                f"{_object_prefix(user_id)}/job-applications/{application_id}/"
                f"resume-{uuid.uuid4().hex}.json"
            )
            object_store.put(
                snapshot_key,
                application_resume_snapshot(source, variant),
                "application/json",
            )
            stored_replacement = True

        try:
            row = resume_store.update_job_application(
                user_id=user_id,
                application_id=application_id,
                company_name=payload.company_name,
                job_title=payload.job_title,
                job_url=payload.job_url,
                location=payload.location,
                work_arrangement=payload.work_arrangement,
                employment_type=payload.employment_type,
                status=payload.status,
                applied_on=payload.applied_on,
                next_action_on=payload.next_action_on,
                notes=payload.notes,
                resume_source_id=str(source_id) if source_id else None,
                resume_variant_id=str(variant_id) if variant_id else None,
                resume_name=resume_name,
                resume_target_role=resume_target_role,
                resume_snapshot_object_key=snapshot_key,
            )
        except Exception:
            if stored_replacement:
                object_store.delete(snapshot_key)
            raise
        assert row is not None
        if stored_replacement:
            object_store.delete(previous_snapshot_key)
        return _job_application_summary(row)

    @app.delete(
        "/api/v1/job-applications/{application_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["job tracker"],
    )
    def delete_job_application(
        application_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> Response:
        existing = resume_store.get_job_application(user_id, application_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Job application not found.")
        interview_brief = resume_store.get_interview_brief(user_id, application_id)
        object_store.delete(str(existing["resume_snapshot_object_key"]))
        if interview_brief is not None:
            object_store.delete(str(interview_brief["object_key"]))
        if not resume_store.delete_job_application(user_id, application_id):
            raise HTTPException(status_code=404, detail="Job application not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def interview_brief_response(row: dict[str, object]) -> InterviewBrief:
        try:
            payload = decode_json(object_store.get(str(row["object_key"])))
            return InterviewBrief(
                id=str(row["id"]),
                application_id=str(row["application_id"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                **payload,
            )
        except (KeyError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The interview brief is temporarily unavailable.",
            ) from error

    @app.get(
        "/api/v1/job-applications/{application_id}/interview-brief",
        response_model=InterviewBrief,
        tags=["job tracker"],
    )
    def get_interview_brief(
        application_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> InterviewBrief:
        if resume_store.get_job_application(user_id, application_id) is None:
            raise HTTPException(status_code=404, detail="Job application not found.")
        row = resume_store.get_interview_brief(user_id, application_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Interview brief not found.")
        return interview_brief_response(row)

    @app.post(
        "/api/v1/job-applications/{application_id}/interview-brief",
        response_model=InterviewBrief,
        tags=["job tracker"],
    )
    def create_interview_brief(
        application_id: str,
        payload: InterviewBriefRequest,
        user_id: Annotated[str, Depends(require_user)],
    ) -> InterviewBrief:
        application = resume_store.get_job_application(user_id, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail="Job application not found.")
        try:
            resume = decode_json(
                object_store.get(str(application["resume_snapshot_object_key"]))
            )
        except (KeyError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The attached resume snapshot is temporarily unavailable.",
            ) from error
        try:
            generated = brief_generator(
                application=application,
                resume=resume,
                job_description=payload.job_description,
                focus=payload.focus,
            )
            validated = InterviewBrief(
                id="pending",
                application_id=application_id,
                created_at="pending",
                updated_at="pending",
                **generated,
            )
        except InterviewBriefInputError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error
        except ProviderError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI interview preparation is temporarily unavailable.",
            ) from error
        except (TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI interview preparation returned an invalid brief.",
            ) from error

        brief_payload = validated.model_dump(
            exclude={"id", "application_id", "created_at", "updated_at"}
        )
        existing = resume_store.get_interview_brief(user_id, application_id)
        object_key = (
            f"{_object_prefix(user_id)}/job-applications/{application_id}/"
            f"interview-brief-{uuid.uuid4().hex}.json"
        )
        object_store.put(object_key, encode_json(brief_payload), "application/json")
        try:
            row = resume_store.upsert_interview_brief(
                user_id=user_id,
                application_id=application_id,
                object_key=object_key,
                model=str(brief_payload["model"]),
            )
        except Exception:
            object_store.delete(object_key)
            raise
        if row is None:
            object_store.delete(object_key)
            raise HTTPException(status_code=404, detail="Job application not found.")
        if existing is not None:
            object_store.delete(str(existing["object_key"]))
        return interview_brief_response(row)

    @app.get(
        "/api/v1/job-matches",
        response_model=list[JobMatchSummary],
        tags=["job matching"],
    )
    def list_job_matches(
        user_id: Annotated[str, Depends(require_user)],
    ) -> list[JobMatchSummary]:
        return [
            JobMatchSummary(
                **row,
                match_label=_job_match_label(row["match_state"]),
            )
            for row in resume_store.list_job_matches(user_id)
        ]

    @app.get(
        "/api/v1/job-matches/{match_id}",
        response_model=JobMatchDetail,
        tags=["job matching"],
    )
    def get_job_match(
        match_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> JobMatchDetail:
        match = resume_store.get_job_match(user_id, match_id)
        if match is None:
            raise HTTPException(status_code=404, detail="Job match not found.")
        source = resume_store.get_source(user_id, str(match["source_id"]))
        if source is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        try:
            analysis = JobMatchAnalysis(
                **decode_json(object_store.get(str(match["analysis_object_key"])))
            )
        except (KeyError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Job match data is temporarily unavailable.",
            ) from error
        return JobMatchDetail(
            id=str(match["id"]),
            source_id=str(match["source_id"]),
            resume_name=str(source["display_name"]),
            target_role=str(match["target_role"]),
            company=str(match["company"]) if match["company"] else None,
            created_at=str(match["created_at"]),
            documents=[
                _job_document_summary(row)
                for row in resume_store.list_job_match_documents(user_id, match_id)
            ],
            **analysis.model_dump(),
        )

    @app.get(
        "/api/v1/forge-ai/threads",
        response_model=list[ForgeAIThreadSummary],
        tags=["forge ai"],
    )
    def list_forge_ai_threads(
        user_id: Annotated[str, Depends(require_user)],
    ) -> list[ForgeAIThreadSummary]:
        return [
            ForgeAIThreadSummary(**row)
            for row in resume_store.list_forge_ai_threads(user_id)
        ]

    @app.post(
        "/api/v1/forge-ai/threads",
        response_model=ForgeAIThreadDetail,
        status_code=status.HTTP_201_CREATED,
        tags=["forge ai"],
    )
    def create_forge_ai_thread(
        payload: ForgeAIThreadCreate,
        user_id: Annotated[str, Depends(require_user)],
    ) -> ForgeAIThreadDetail:
        match = resume_store.get_job_match(user_id, payload.match_id)
        if match is None:
            raise HTTPException(status_code=404, detail="Job match not found.")
        source = resume_store.get_source(user_id, str(match["source_id"]))
        if source is None:
            raise HTTPException(status_code=404, detail="Resume not found.")

        existing = resume_store.get_forge_ai_thread_for_match(user_id, payload.match_id)
        if existing is not None:
            return forge_ai_thread_detail(user_id, existing)
        try:
            analysis = JobMatchAnalysis(
                **decode_json(object_store.get(str(match["analysis_object_key"])))
            )
        except (KeyError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Job match data is temporarily unavailable.",
            ) from error

        questions = [
            f"What specific project, action, and outcome can verify your {keyword} experience?"
            for keyword in analysis.missing_keywords[:6]
        ]
        memory = ForgeAIMemory(
            summary=(
                f"Evidence review for {match['target_role']} begins at "
                f"{analysis.match_percentage}% resume coverage."
            ),
            confirmed_facts=[],
            rejected_claims=[],
            open_questions=questions,
            decisions=[
                "Unsupported claims stay out of the tailored resume.",
                "The uploaded resume source remains immutable.",
            ],
        )
        thread = resume_store.create_forge_ai_thread(
            user_id=user_id,
            match_id=payload.match_id,
            source_id=str(match["source_id"]),
            title=str(match["target_role"]),
            baseline_score=analysis.match_percentage,
            memory_json=memory.model_dump_json(),
            status="ready" if analysis.match_percentage >= 80 else "active",
        )
        if thread is None:
            raise HTTPException(status_code=404, detail="Job match not found.")

        if analysis.match_percentage >= 80:
            opening = (
                f"Your saved resume currently supports {analysis.match_percentage}% of this "
                "role's priority language. We can now inspect the strongest evidence and make "
                "sure every tailored statement remains defensible."
            )
            opening_status = "verified"
        elif analysis.missing_keywords:
            opening = (
                f"The saved analysis starts at {analysis.match_percentage}% evidence coverage. "
                "I will only raise that score when your resume or a concrete fact you confirm "
                f"supports it. First: what real project, action, and outcome demonstrate "
                f"{analysis.missing_keywords[0]}?"
            )
            opening_status = "needs_evidence"
        else:
            opening = (
                f"The saved analysis starts at {analysis.match_percentage}% evidence coverage. "
                "Tell me which requirement you want to examine, and we will test it against "
                "facts you can defend in an interview."
            )
            opening_status = "needs_evidence"
        resume_store.create_forge_ai_message(
            user_id=user_id,
            thread_id=str(thread["id"]),
            role="assistant",
            content=opening,
            citations_json="[]",
            claim_status=opening_status,
            model=None,
        )
        refreshed = resume_store.get_forge_ai_thread(user_id, str(thread["id"]))
        assert refreshed is not None
        return forge_ai_thread_detail(user_id, refreshed)

    @app.get(
        "/api/v1/forge-ai/threads/{thread_id}",
        response_model=ForgeAIThreadDetail,
        tags=["forge ai"],
    )
    def get_forge_ai_thread(
        thread_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> ForgeAIThreadDetail:
        thread = resume_store.get_forge_ai_thread(user_id, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="Forge AI workspace not found.")
        return forge_ai_thread_detail(user_id, thread)

    @app.post(
        "/api/v1/forge-ai/threads/{thread_id}/messages",
        response_model=ForgeAIThreadDetail,
        status_code=status.HTTP_201_CREATED,
        tags=["forge ai"],
    )
    def create_forge_ai_message(
        thread_id: str,
        payload: ForgeAIMessageCreate,
        user_id: Annotated[str, Depends(require_user)],
    ) -> ForgeAIThreadDetail:
        thread = resume_store.get_forge_ai_thread(user_id, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="Forge AI workspace not found.")
        user_message = payload.content.strip()
        if not user_message:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Write a message before sending it.",
            )

        match, _, resume, job_description, saved_analysis, memory, _ = (
            forge_ai_context(user_id, thread)
        )
        recent_messages = [
            {
                "role": row["role"],
                "content": row["content"],
                "citations": json.loads(str(row["citations_json"])),
            }
            for row in resume_store.list_forge_ai_messages(user_id, thread_id)
        ]
        website_contexts: list[dict[str, object]] = []
        for linked_url in extract_public_urls(user_message):
            try:
                website_context = website_reader(
                    url=linked_url,
                    user_message=user_message,
                )
                if isinstance(website_context, dict):
                    website_contexts.append(website_context)
                else:
                    website_contexts.append(website_context.as_prompt_dict())
            except ProviderError:
                website_contexts.append(
                    {
                        "status": "unavailable",
                        "requestedUrl": linked_url,
                        "error": "The public page could not be read.",
                    }
                )
        try:
            generated = coach_generator(
                target_role=str(match["target_role"]),
                company=str(match["company"]) if match["company"] else None,
                job_description=job_description,
                saved_analysis=saved_analysis.model_dump(mode="json"),
                resume=resume,
                memory=memory.model_dump(mode="json"),
                recent_messages=recent_messages,
                user_message=user_message,
                website_contexts=website_contexts,
            )
            next_memory = ForgeAIMemory(**generated["memory"])
            assistant_message = str(generated["assistant_message"]).strip()
            claim_status = str(generated["claim_status"])
            citations = generated["citation_details"]
            model = str(generated["model"])
            if not assistant_message or claim_status not in {
                "verified",
                "user_confirmed",
                "needs_evidence",
                "gap",
            }:
                raise ValueError("invalid Forge AI response")
            ForgeAIMessage(
                id="validation",
                thread_id=thread_id,
                role="assistant",
                content=assistant_message,
                citations=citations,
                claim_status=claim_status,
                model=model,
                created_at="validation",
            )
        except ProviderError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Forge AI is temporarily unavailable. "
                    "Your evidence workspace is unchanged."
                ),
            ) from error
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Forge AI returned an invalid response. Your evidence workspace is unchanged.",
            ) from error

        user_facts = "\n".join(
            fact.fact for fact in next_memory.confirmed_facts if fact.source == "user"
        )
        evidence_text = draft_to_evidence_text(resume)
        if user_facts:
            evidence_text = f"{evidence_text}\n{user_facts}"
        current_analysis = analyze_job_match(
            target_role=str(match["target_role"]),
            company=str(match["company"]) if match["company"] else None,
            job_description=job_description,
            resume_text=evidence_text,
        )

        resume_store.create_forge_ai_message(
            user_id=user_id,
            thread_id=thread_id,
            role="user",
            content=user_message,
            citations_json="[]",
            claim_status="needs_evidence",
            model=None,
        )
        resume_store.create_forge_ai_message(
            user_id=user_id,
            thread_id=thread_id,
            role="assistant",
            content=assistant_message,
            citations_json=json.dumps(citations, ensure_ascii=False),
            claim_status=claim_status,
            model=model,
        )
        updated = resume_store.update_forge_ai_thread(
            user_id=user_id,
            thread_id=thread_id,
            current_score=current_analysis.match_percentage,
            status="ready" if current_analysis.match_percentage >= 80 else "active",
            memory_json=next_memory.model_dump_json(),
            model=model,
        )
        assert updated is not None
        return forge_ai_thread_detail(user_id, updated)

    @app.post(
        "/api/v1/forge-ai/threads/{thread_id}/enhance",
        response_model=ForgeAIEnhancementResult,
        status_code=status.HTTP_201_CREATED,
        tags=["forge ai"],
    )
    def enhance_resume_with_forge_ai(
        thread_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> ForgeAIEnhancementResult:
        thread = resume_store.get_forge_ai_thread(user_id, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="Forge AI workspace not found.")
        match, source, resume, job_description, saved_analysis, memory, analysis = (
            forge_ai_context(user_id, thread)
        )
        try:
            generated = enhancement_generator(
                target_role=str(match["target_role"]),
                company=str(match["company"]) if match["company"] else None,
                job_description=job_description,
                saved_analysis=saved_analysis.model_dump(mode="json"),
                resume=resume,
                memory=memory.model_dump(mode="json"),
            )
            enhanced = generated["draft"]
            if not isinstance(enhanced, dict):
                raise TypeError("enhanced resume must be an object")
            enhanced = tailor_resume_draft(
                enhanced,
                target_role=str(match["target_role"]),
                matched_keywords=analysis.matched_keywords,
            )
            overview = str(generated["overview"]).strip()
            changed_sections = generated["changed_sections"]
            operations = generated["operations"]
            gaps = generated["gaps"]
            model = str(generated["model"])
            if not overview or not model:
                raise ValueError("invalid enhancement response")
        except ResumeEnhancementUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{error}. Forge AI will not manufacture content to force a better fit."
                ),
            ) from error
        except ProviderError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Forge AI could not build the enhanced resume right now. "
                    "Your source and evidence discussion are unchanged."
                ),
            ) from error
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Forge AI returned an invalid enhancement. Nothing was changed.",
            ) from error

        projected_analysis = analyze_job_match(
            target_role=str(match["target_role"]),
            company=str(match["company"]) if match["company"] else None,
            job_description=job_description,
            resume_text=draft_to_evidence_text(enhanced),
        )
        document_payload, _, _ = _render_resume_docx(
            draft=enhanced,
            title=f"{source['display_name']} — {match['target_role']} — Forge enhanced",
            description=(
                "Evidence-cited enhanced resume generated from an immutable source "
                "and a private Forge AI discussion."
            ),
        )
        safe_role = re.sub(
            r"[^A-Za-z0-9._-]+", "-", str(match["target_role"])
        ).strip("-.")
        base_filename = f"{safe_role or 'role'}-forge-enhanced-resume"
        try:
            pdf_payload = converter.docx_to_pdf(
                document_payload, f"{base_filename}.docx"
            )
        except DocumentConversionError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The PDF converter is temporarily unavailable.",
            ) from error

        generation_id = uuid.uuid4().hex
        object_prefix = (
            f"{_object_prefix(user_id)}/job-matches/{match['id']}/"
            f"forge-ai/{thread_id}/{generation_id}"
        )
        artifacts = [
            {
                "filename": f"{base_filename}.docx",
                "media_type": DOCX_MEDIA_TYPE,
                "object_key": f"{object_prefix}.docx",
                "payload": document_payload,
            },
            {
                "filename": f"{base_filename}.pdf",
                "media_type": PDF_MEDIA_TYPE,
                "object_key": f"{object_prefix}.pdf",
                "payload": pdf_payload,
            },
        ]
        stored_keys: list[str] = []
        try:
            for artifact in artifacts:
                object_store.put(
                    str(artifact["object_key"]),
                    bytes(artifact["payload"]),
                    str(artifact["media_type"]),
                )
                stored_keys.append(str(artifact["object_key"]))
            rows = resume_store.create_job_match_documents(
                user_id=user_id,
                match_id=str(match["id"]),
                documents=[
                    {
                        "filename": str(artifact["filename"]),
                        "media_type": str(artifact["media_type"]),
                        "object_key": str(artifact["object_key"]),
                    }
                    for artifact in artifacts
                ],
            )
        except Exception:
            for key in stored_keys:
                object_store.delete(key)
            raise
        assert rows is not None
        unique_citations: dict[str, dict[str, object]] = {}
        audit_lines: list[str] = []
        uses_user_confirmed = False
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            after = operation.get("after")
            rendered_after = (
                ", ".join(str(value) for value in after)
                if isinstance(after, list)
                else str(after or "")
            )
            audit_lines.append(
                f"- {operation.get('section', 'Resume')}: {rendered_after}"
            )
            evidence_items = operation.get("evidence")
            if not isinstance(evidence_items, list):
                continue
            for evidence_item in evidence_items:
                if not isinstance(evidence_item, dict):
                    continue
                identifier = str(evidence_item.get("id") or "")
                label = str(evidence_item.get("label") or "")
                if identifier and label:
                    unique_citations[identifier] = {"id": identifier, "label": label}
                if evidence_item.get("source") == "user_confirmed":
                    uses_user_confirmed = True
        audit_message = (
            f"Built an enhanced resume with {len(audit_lines)} audited "
            f"{'change' if len(audit_lines) == 1 else 'changes'} and projected "
            f"{projected_analysis.match_percentage}% evidence coverage.\n\n"
            "**Applied changes**\n"
            + "\n".join(audit_lines)
        )
        if gaps:
            audit_message += "\n\n**Requirements still unsupported**\n" + "\n".join(
                f"- {gap}" for gap in gaps
            )
        resume_store.create_forge_ai_message(
            user_id=user_id,
            thread_id=thread_id,
            role="assistant",
            content=audit_message,
            citations_json=json.dumps(list(unique_citations.values()), ensure_ascii=False),
            claim_status="user_confirmed" if uses_user_confirmed else "verified",
            model=model,
        )
        return ForgeAIEnhancementResult(
            projected_score=projected_analysis.match_percentage,
            overview=overview,
            changed_sections=changed_sections,
            operations=operations,
            gaps=gaps,
            documents=[_job_document_summary(row) for row in rows],
            model=model,
        )

    @app.post(
        "/api/v1/job-matches",
        response_model=JobMatchResult,
        status_code=status.HTTP_201_CREATED,
        tags=["job matching"],
    )
    def create_job_match(
        user_id: Annotated[str, Depends(require_user)],
        source_id: Annotated[str, Form(min_length=1)],
        target_role: Annotated[str, Form(min_length=2, max_length=160)],
        company: Annotated[str | None, Form(max_length=160)] = None,
        job_description: Annotated[str | None, Form(max_length=20_000)] = None,
        files: Annotated[list[UploadFile] | None, File()] = None,
    ) -> JobMatchResult:
        clean_role = target_role.strip()
        if len(clean_role) < 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Target role must contain at least two characters.",
            )
        clean_company = company.strip() if company and company.strip() else None
        source = resume_store.get_source(user_id, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        try:
            draft = decode_json(object_store.get(str(source["draft_object_key"])))
        except KeyError as error:
            raise HTTPException(status_code=503, detail="Resume draft is unavailable.") from error
        resume_text = draft_to_evidence_text(draft)
        if len(resume_text) < 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The selected resume needs at least 100 characters of reviewed content.",
            )

        uploads = files or []
        if len(uploads) > resolved_settings.max_resume_files:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Upload no more than {resolved_settings.max_resume_files} job-description files.",
            )
        parts = [job_description or ""]
        for upload in uploads:
            filename = _safe_filename(upload.filename or "", "job-description")
            suffix = Path(filename).suffix.casefold()
            if suffix not in JOB_FILE_SUFFIXES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Use PDF, DOCX, TXT, PNG, JPG, or JPEG job-description files.",
                )
            payload = upload.file.read(resolved_settings.max_resume_bytes + 1)
            if len(payload) > resolved_settings.max_resume_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Job-description files are limited to 10 MB each.",
                )
            try:
                if suffix in IMAGE_SUFFIXES:
                    parts.append(converter.image_to_text(payload, filename))
                else:
                    parts.append(extract_job_document(filename, payload))
            except ResumeImportError as error:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(error),
                ) from error
            except DocumentConversionError as error:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Image text extraction is temporarily unavailable.",
                ) from error

        try:
            combined_description = combine_job_description(parts)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error
        analysis = analyze_job_match(
            target_role=clean_role,
            company=clean_company,
            job_description=combined_description,
            resume_text=resume_text,
        )
        match_id = "jmt_" + uuid.uuid4().hex
        prefix = f"{_object_prefix(user_id)}/job-matches/{match_id}"
        description_key = f"{prefix}/job-description.txt"
        resume_snapshot_key = f"{prefix}/resume.json"
        analysis_key = f"{prefix}/analysis.json"
        stored_keys: list[str] = []
        try:
            object_store.put(
                description_key,
                combined_description.encode("utf-8"),
                "text/plain; charset=utf-8",
            )
            stored_keys.append(description_key)
            object_store.put(
                resume_snapshot_key,
                encode_json(draft),
                "application/json",
            )
            stored_keys.append(resume_snapshot_key)
            object_store.put(
                analysis_key,
                encode_json(analysis.model_dump()),
                "application/json",
            )
            stored_keys.append(analysis_key)
            row = resume_store.create_job_match(
                match_id=match_id,
                user_id=user_id,
                source_id=source_id,
                target_role=clean_role,
                company=clean_company,
                job_description_object_key=description_key,
                resume_snapshot_object_key=resume_snapshot_key,
                analysis_object_key=analysis_key,
                match_state=analysis.match_state,
                match_percentage=analysis.match_percentage,
            )
        except Exception:
            for key in stored_keys:
                object_store.delete(key)
            raise
        assert row is not None
        return JobMatchResult(
            id=match_id,
            source_id=source_id,
            resume_name=str(source["display_name"]),
            target_role=clean_role,
            company=clean_company,
            created_at=str(row["created_at"]),
            **analysis.model_dump(),
        )

    @app.post(
        "/api/v1/job-matches/{match_id}/tailor",
        response_model=JobMatchDocumentBundle,
        status_code=status.HTTP_201_CREATED,
        tags=["job matching"],
    )
    def tailor_job_match(
        match_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> JobMatchDocumentBundle:
        match = resume_store.get_job_match(user_id, match_id)
        if match is None:
            raise HTTPException(status_code=404, detail="Job match not found.")
        if str(match["match_state"]) == "no_match":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This role is not a match, so a tailored resume was not generated.",
            )
        source = resume_store.get_source(user_id, str(match["source_id"]))
        if source is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        try:
            draft = decode_json(
                object_store.get(str(match["resume_snapshot_object_key"]))
            )
            analysis = JobMatchAnalysis(
                **decode_json(object_store.get(str(match["analysis_object_key"])))
            )
        except KeyError as error:
            raise HTTPException(status_code=503, detail="Job match data is unavailable.") from error
        tailored = tailor_resume_draft(
            draft,
            target_role=str(match["target_role"]),
            matched_keywords=analysis.matched_keywords,
        )
        document_payload, _, _ = _render_resume_docx(
            draft=tailored,
            title=f"{source['display_name']} — {match['target_role']}",
            description="Evidence-grounded tailored resume generated by Axelyn Forge.",
        )
        safe_role = re.sub(
            r"[^A-Za-z0-9._-]+", "-", str(match["target_role"])
        ).strip("-.")
        base_filename = f"{safe_role or 'role'}-tailored-resume"
        try:
            pdf_payload = converter.docx_to_pdf(
                document_payload, f"{base_filename}.docx"
            )
        except DocumentConversionError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The LibreOffice PDF converter is temporarily unavailable.",
            ) from error
        generation_id = uuid.uuid4().hex
        object_prefix = (
            f"{_object_prefix(user_id)}/job-matches/{match_id}/documents/{generation_id}"
        )
        artifacts = [
            {
                "filename": f"{base_filename}.docx",
                "media_type": DOCX_MEDIA_TYPE,
                "object_key": f"{object_prefix}.docx",
                "payload": document_payload,
            },
            {
                "filename": f"{base_filename}.pdf",
                "media_type": PDF_MEDIA_TYPE,
                "object_key": f"{object_prefix}.pdf",
                "payload": pdf_payload,
            },
        ]
        stored_keys = []
        try:
            for artifact in artifacts:
                object_store.put(
                    str(artifact["object_key"]),
                    bytes(artifact["payload"]),
                    str(artifact["media_type"]),
                )
                stored_keys.append(str(artifact["object_key"]))
            rows = resume_store.create_job_match_documents(
                user_id=user_id,
                match_id=match_id,
                documents=[
                    {
                        "filename": str(artifact["filename"]),
                        "media_type": str(artifact["media_type"]),
                        "object_key": str(artifact["object_key"]),
                    }
                    for artifact in artifacts
                ],
            )
        except Exception:
            for key in stored_keys:
                object_store.delete(key)
            raise
        assert rows is not None
        return JobMatchDocumentBundle(
            documents=[_job_document_summary(row) for row in rows]
        )

    @app.get(
        "/api/v1/job-match-documents/{document_id}/download",
        tags=["job matching"],
    )
    def download_job_match_document(
        document_id: str,
        user_id: Annotated[str, Depends(require_user)],
    ) -> Response:
        document = resume_store.get_job_match_document(user_id, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        try:
            payload = object_store.get(str(document["object_key"]))
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Document not found.") from error
        filename = _safe_filename(str(document["filename"]), "tailored-resume.docx")
        return Response(
            payload,
            media_type=str(document["media_type"]),
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "axelyn_api.main:app",
        host=os.environ.get("FORGE_HOST", "0.0.0.0"),
        port=int(os.environ.get("FORGE_PORT", "8000")),
        reload=False,
    )
