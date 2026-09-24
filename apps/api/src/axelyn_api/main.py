"""FastAPI application factory and production entry point."""

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .analysis import analyze_forge_brief
from .catalog import SERVICE_IDS, SERVICES
from .config import Settings
from .models import (
    HealthResponse,
    ForgeBriefAccepted,
    ForgeBriefCreate,
    Service,
    ServiceRequestAccepted,
    ServiceRequestCreate,
)
from .store import ServiceRequestStore


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    resolved_settings = settings or Settings.from_environ()
    store = ServiceRequestStore(resolved_settings.database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        store.initialize()
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

    if resolved_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type"],
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
    ) -> ForgeBriefAccepted:
        analysis = analyze_forge_brief(payload)
        return request.app.state.service_request_store.create_forge_brief(
            payload,
            analysis,
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
