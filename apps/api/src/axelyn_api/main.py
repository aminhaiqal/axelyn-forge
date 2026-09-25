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
from forge.docx import render_docx, update_docx_core_properties

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
from .models import (
    HealthResponse,
    AuthenticatedUser,
    ForgeBriefAccepted,
    ForgeBriefCreate,
    GeneratedDocumentBundle,
    GeneratedDocumentSummary,
    ResumeAcceptRequest,
    ResumeDraft,
    ResumeDraftUpdate,
    ResumeImportItem,
    ResumeImportResponse,
    ResumeSourceDetail,
    ResumeSourceSummary,
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
    standard_template_values,
)
from .resume_store import ResumeStore
from .storage import create_object_store
from .store import ServiceRequestStore


def _source_summary(row: dict[str, object]) -> ResumeSourceSummary:
    return ResumeSourceSummary(**row)


def _variant_summary(row: dict[str, object]) -> ResumeVariantSummary:
    return ResumeVariantSummary(**row)


def _document_summary(row: dict[str, object]) -> GeneratedDocumentSummary:
    return GeneratedDocumentSummary(**row)


def _safe_filename(value: str, fallback: str) -> str:
    filename = Path(value).name.strip()[:180]
    return filename or fallback


def _object_prefix(user_id: str) -> str:
    owner_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]
    return f"users/{owner_hash}"


def _editable_draft(payload: ResumeDraftUpdate) -> dict[str, object]:
    normalized = normalize_resume_text(payload.extracted_text)
    return {
        "display_name": payload.display_name,
        "target_role": payload.target_role,
        "full_name": payload.full_name,
        "headline": payload.headline,
        "contact_line": payload.contact_line,
        "summary": payload.summary,
        "extracted_text": payload.extracted_text,
        "sections": normalized.get("sections", {}),
    }


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
        return ResumeSourceDetail(**row, draft=ResumeDraft(**draft))

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
        object_store.put(str(row["draft_object_key"]), encode_json(draft), "application/json")
        updated = resume_store.update_source(
            user_id=user_id,
            source_id=source_id,
            display_name=payload.display_name,
            target_role=payload.target_role,
            draft_object_key=str(row["draft_object_key"]),
            status="needs_review" if payload.extracted_text else "needs_ocr",
            warning=None if payload.extracted_text else str(row.get("warning") or "Text is required."),
        )
        assert updated is not None
        return ResumeSourceDetail(**updated, draft=ResumeDraft(**draft))

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
        if not payload.extracted_text.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Add resume text before accepting this version.",
            )
        draft = _editable_draft(payload)
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
        template = resolved_settings.resume_template_path
        if not template.is_file():
            raise HTTPException(status_code=503, detail="The standard resume template is unavailable.")
        try:
            normalized = decode_json(
                object_store.get(str(variant["normalized_object_key"]))
            )
        except KeyError as error:
            raise HTTPException(status_code=503, detail="Resume data is unavailable.") from error

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "resume.docx"
            render_docx(template, output, standard_template_values(normalized), strict=True)
            update_docx_core_properties(
                output,
                {
                    "title": str(variant["name"]),
                    "subject": "Axelyn Forge standard resume",
                    "description": "Resume generated from user-approved source material.",
                    "keywords": "resume, axelyn forge",
                },
            )
            document_payload = output.read_bytes()

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
                        "template_id": "axelyn-standard-resume",
                        "template_version": "1",
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

    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "axelyn_api.main:app",
        host=os.environ.get("FORGE_HOST", "0.0.0.0"),
        port=int(os.environ.get("FORGE_PORT", "8000")),
        reload=False,
    )
