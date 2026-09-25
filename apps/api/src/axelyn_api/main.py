"""FastAPI application factory and production entry point."""

import hashlib
import os
import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator, Optional

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from . import __version__
from .analysis import analyze_forge_brief
from .auth import ClerkAuthenticator, UserAuthenticator
from .catalog import SERVICE_IDS, SERVICES
from .config import Settings
from .converter import (
    DocumentConversionError,
    DocumentConverter,
    create_document_converter,
)
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
    HealthResponse,
    AuthenticatedUser,
    ForgeBriefAccepted,
    ForgeBriefCreate,
    GeneratedDocumentBundle,
    GeneratedDocumentSummary,
    JobMatchAnalysis,
    JobMatchDocumentBundle,
    JobMatchDocumentSummary,
    JobMatchResult,
    ResumeAcceptRequest,
    ResumeDraft,
    ResumeDraftUpdate,
    ResumeImportItem,
    ResumeImportResponse,
    ResumeSourceDetail,
    ResumeSourceSummary,
    ResumeTemplateSummary,
    ResumeVariantSummary,
    Service,
    ServiceRequestAccepted,
    ServiceRequestCreate,
)
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
from .resume_store import ResumeStore
from .resume_templates import render_resume, template_catalog
from .storage import create_object_store
from .store import ServiceRequestStore


def _source_summary(row: dict[str, object]) -> ResumeSourceSummary:
    return ResumeSourceSummary(**row)


def _variant_summary(row: dict[str, object]) -> ResumeVariantSummary:
    return ResumeVariantSummary(**row)


def _document_summary(row: dict[str, object]) -> GeneratedDocumentSummary:
    return GeneratedDocumentSummary(**row)


def _job_document_summary(row: dict[str, object]) -> JobMatchDocumentSummary:
    return JobMatchDocumentSummary(**row)


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


def _editable_draft(payload: ResumeDraftUpdate) -> dict[str, object]:
    sections = payload.sections
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
        "contact_line": payload.contact_line,
        "summary": payload.summary,
        "extracted_text": payload.extracted_text,
        "sections": sections,
        "custom_sections": custom_sections,
    }


def _render_resume_docx(
    *,
    draft: dict[str, object],
    title: str,
    description: str,
) -> tuple[bytes, str, str]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        output = Path(temporary_directory) / "resume.docx"
        template_id, template_version = render_resume(
            draft=draft,
            output=output,
            title=title,
            description=description,
        )
        return output.read_bytes(), template_id, template_version


def create_app(
    settings: Optional[Settings] = None,
    authenticate_user: Optional[UserAuthenticator] = None,
    document_converter: Optional[DocumentConverter] = None,
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

    def require_user(request: Request) -> str:
        return user_authenticator(request)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        resume_store.initialize()
        yield

    app = FastAPI(
        title="Axelyn Forge API",
        summary="Service intake and evidence alignment for Axelyn Forge.",
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

    @app.post(
        "/api/v1/forge-briefs",
        response_model=ForgeBriefAccepted,
        status_code=status.HTTP_201_CREATED,
        tags=["forge"],
    )
    def create_forge_brief(
        payload: ForgeBriefCreate,
        request: Request,
        user_id: Annotated[str, Depends(require_user)],
    ) -> ForgeBriefAccepted:
        analysis = analyze_forge_brief(payload)
        return request.app.state.service_request_store.create_forge_brief(
            payload,
            analysis,
            user_id,
        )

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
                media_type="application/vnd.axelyn.resume+json",
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

            source_id = "src_" + uuid.uuid4().hex
            suffix = Path(original_name).suffix.casefold()
            stem = Path(original_name).stem.strip()[:160] or "Imported resume"
            prefix = f"{owner_prefix}/sources/{source_id}"
            original_key = f"{prefix}/original{suffix}"
            draft_key = f"{prefix}/draft.json"
            draft = draft_payload(
                extracted_text=extracted.text,
                display_name=stem,
                target_role=clean_role,
            )
            resume_status = "needs_ocr" if not extracted.text else "needs_review"
            try:
                object_store.put(original_key, payload, extracted.media_type)
                object_store.put(draft_key, encode_json(draft), "application/json")
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
                    status=resume_status,
                    warning=extracted.warning,
                )
            except Exception:
                object_store.delete(original_key)
                object_store.delete(draft_key)
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
        try:
            draft = decode_json(object_store.get(str(row["draft_object_key"])))
        except KeyError as error:
            raise HTTPException(status_code=503, detail="Resume draft is unavailable.") from error
        return _source_detail(row, draft)

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
