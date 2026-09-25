"""Clerk session verification for protected Forge API resources."""

from typing import Callable

from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
from fastapi import HTTPException, Request, status

from .config import Settings


UserAuthenticator = Callable[[Request], str]


class ClerkAuthenticator:
    def __init__(self, settings: Settings):
        self.settings = settings

    def __call__(self, request: Request) -> str:
        if not self.settings.clerk_secret_key and not self.settings.clerk_jwt_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is not configured.",
            )

        try:
            auth_state = authenticate_request(
                request,
                AuthenticateRequestOptions(
                    secret_key=self.settings.clerk_secret_key,
                    jwt_key=self.settings.clerk_jwt_key,
                    authorized_parties=list(
                        self.settings.clerk_authorized_parties
                    ),
                    accepts_token=["session_token"],
                ),
            )
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid authentication is required.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from error

        user_id = auth_state.payload.get("sub") if auth_state.payload else None
        if not auth_state.is_signed_in or not isinstance(user_id, str):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid authentication is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user_id
