from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from httpx import RequestError
from pydantic import ValidationError
from supabase import Client, create_client
from supabase_auth.errors import (
    AuthApiError,
    AuthInvalidJwtError,
    AuthRetryableError,
    AuthUnknownError,
)


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID


def _authentication_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


@cache
def _get_supabase_client() -> Client:
    from config import settings

    url = getattr(settings, "supabase_url", None)
    publishable_key = getattr(settings, "supabase_publishable_key", None)
    if url is None or publishable_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is unavailable",
        )

    normalized_url = url.strip()
    normalized_key = publishable_key.get_secret_value().strip()
    if not normalized_url or not normalized_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is unavailable",
        )
    return create_client(normalized_url, normalized_key)


def _authentication_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication is unavailable",
    )


def _is_token_api_error(error: AuthApiError) -> bool:
    return error.status == 401 or error.code in {
        "bad_jwt",
        "invalid_jwt",
        "no_authorization",
        "unexpected_audience",
    }


def get_authenticated_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_error("Authentication required")

    try:
        response = _get_supabase_client().auth.get_claims(credentials.credentials)
    except AuthInvalidJwtError as error:
        raise _authentication_error(
            "Invalid or expired authentication token"
        ) from error
    except AuthApiError as error:
        if _is_token_api_error(error):
            raise _authentication_error(
                "Invalid or expired authentication token"
            ) from error
        raise _authentication_unavailable() from error
    except (
        AuthRetryableError,
        AuthUnknownError,
        RequestError,
        ValidationError,
    ) as error:
        raise _authentication_unavailable() from error

    claims: Any = response.get("claims") if isinstance(response, Mapping) else None
    subject = claims.get("sub") if isinstance(claims, Mapping) else None
    try:
        user_id = UUID(subject) if isinstance(subject, str) else None
    except ValueError as error:
        raise _authentication_error(
            "Invalid or expired authentication token"
        ) from error
    if user_id is None:
        raise _authentication_error("Invalid or expired authentication token")

    return AuthenticatedUser(id=user_id)


def require_admin(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> AuthenticatedUser:
    from config import settings

    admin_user_id = getattr(settings, "admin_user_id", None)
    if admin_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is unavailable",
        )
    if user.id != admin_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
