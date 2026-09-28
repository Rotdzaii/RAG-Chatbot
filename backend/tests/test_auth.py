from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, patch
from uuid import UUID, uuid4

from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from httpx import RequestError
from pydantic import BaseModel, SecretStr, ValidationError
from supabase_auth.errors import (
    AuthApiError,
    AuthInvalidJwtError,
    AuthRetryableError,
    AuthUnknownError,
)


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test",
    supabase_url=None,
    supabase_publishable_key=None,
    admin_user_id=None,
)
sys.modules.setdefault("config", fake_config)

from auth import (  # noqa: E402
    AuthenticatedUser,
    _get_supabase_client,
    get_authenticated_user,
)
from main import app  # noqa: E402
from rag.knowledge_sources import KnowledgeSourcePage  # noqa: E402


TOKEN = "verified-user-access-token"


class ProviderClaimsResponse(BaseModel):
    claims: dict[str, object]


def provider_validation_error() -> ValidationError:
    try:
        ProviderClaimsResponse.model_validate({})
    except ValidationError as error:
        return error
    raise AssertionError("Expected provider response validation to fail")


def auth_config(
    *,
    admin_user_id: UUID | None = None,
    url: str | None = "https://project.supabase.co",
    key: SecretStr | None = SecretStr("publishable-key"),
) -> ModuleType:
    module = ModuleType("config")
    module.settings = SimpleNamespace(
        supabase_url=url,
        supabase_publishable_key=key,
        admin_user_id=admin_user_id,
    )
    return module


class AdminAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        _get_supabase_client.cache_clear()
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        _get_supabase_client.cache_clear()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def test_missing_token_returns_401_without_database_session(self) -> None:
        with patch("rag.admin_router.SessionLocal") as session_local:
            response = self.client.get("/admin/knowledge-sources")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Authentication required"})
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        session_local.assert_not_called()

    def test_invalid_token_returns_401_without_database_session(self) -> None:
        client = Mock()
        client.auth.get_claims.side_effect = AuthInvalidJwtError("invalid token")

        with (
            patch("auth._get_supabase_client", return_value=client),
            patch("rag.admin_router.SessionLocal") as session_local,
        ):
            response = self.client.get(
                "/admin/knowledge-sources",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Invalid or expired authentication token"},
        )
        self.assertNotIn("invalid token", response.text)
        session_local.assert_not_called()

    def test_missing_or_malformed_subject_returns_401(self) -> None:
        invalid_claims = ({"claims": {}}, {"claims": {"sub": "not-a-uuid"}})

        for claims in invalid_claims:
            with self.subTest(claims=claims):
                client = Mock()
                client.auth.get_claims.return_value = claims
                with (
                    patch("auth._get_supabase_client", return_value=client),
                    patch("rag.admin_router.SessionLocal") as session_local,
                ):
                    response = self.client.get(
                        "/admin/knowledge-sources",
                        headers={"Authorization": f"Bearer {TOKEN}"},
                    )

                self.assertEqual(response.status_code, 401)
                self.assertEqual(
                    response.json(),
                    {"detail": "Invalid or expired authentication token"},
                )
                session_local.assert_not_called()

    def test_authenticated_non_admin_returns_403_without_database_session(self) -> None:
        admin_id = uuid4()
        user_id = uuid4()
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            id=user_id
        )

        with (
            patch.dict(sys.modules, {"config": auth_config(admin_user_id=admin_id)}),
            patch("rag.admin_router.SessionLocal") as session_local,
        ):
            response = self.client.get("/admin/knowledge-sources")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Admin access required"})
        session_local.assert_not_called()

    def test_authenticated_configured_admin_can_use_existing_endpoint(self) -> None:
        admin_id = uuid4()
        session = Mock()
        page = KnowledgeSourcePage(items=[], total=0, limit=20, offset=0)
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            id=admin_id
        )

        with (
            patch.dict(sys.modules, {"config": auth_config(admin_user_id=admin_id)}),
            patch("rag.admin_router.SessionLocal", return_value=session),
            patch("rag.admin_router.list_knowledge_sources", return_value=page),
        ):
            response = self.client.get("/admin/knowledge-sources")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"items": [], "total": 0, "limit": 20, "offset": 0}
        )
        session.close.assert_called_once_with()

    def test_missing_auth_configuration_returns_503(self) -> None:
        missing_config = auth_config(admin_user_id=uuid4(), url=None, key=None)

        with (
            patch.dict(sys.modules, {"config": missing_config}),
            patch("rag.admin_router.SessionLocal") as session_local,
        ):
            response = self.client.get(
                "/admin/knowledge-sources",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Authentication is unavailable"})
        session_local.assert_not_called()

    def test_blank_auth_configuration_returns_503_without_database_session(self) -> None:
        blank_config = auth_config(
            admin_user_id=uuid4(),
            url=" \t ",
            key=SecretStr(" \n "),
        )

        with (
            patch.dict(sys.modules, {"config": blank_config}),
            patch("auth.create_client") as create_client,
            patch("rag.admin_router.SessionLocal") as session_local,
        ):
            response = self.client.get(
                "/admin/knowledge-sources",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Authentication is unavailable"})
        create_client.assert_not_called()
        session_local.assert_not_called()

    def test_missing_admin_user_id_returns_503_without_database_session(self) -> None:
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            id=uuid4()
        )

        with (
            patch.dict(
                sys.modules, {"config": auth_config(admin_user_id=None)}
            ),
            patch("rag.admin_router.SessionLocal") as session_local,
        ):
            response = self.client.get("/admin/knowledge-sources")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Authentication is unavailable"})
        session_local.assert_not_called()

    def test_provider_and_network_failures_return_503(self) -> None:
        failures = (
            AuthRetryableError("provider unavailable", 503),
            AuthApiError("provider error", 500, None),
            AuthUnknownError("provider failure", RuntimeError("internal")),
            RequestError("network unavailable"),
        )

        for failure in failures:
            with self.subTest(exception=type(failure).__name__):
                client = Mock()
                client.auth.get_claims.side_effect = failure
                with (
                    patch("auth._get_supabase_client", return_value=client),
                    patch("rag.admin_router.SessionLocal") as session_local,
                ):
                    response = self.client.get(
                        "/admin/knowledge-sources",
                        headers={"Authorization": f"Bearer {TOKEN}"},
                    )

                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json(), {"detail": "Authentication is unavailable"}
                )
                self.assertNotIn(str(failure), response.text)
                session_local.assert_not_called()

    def test_provider_response_validation_failure_returns_503(self) -> None:
        client = Mock()
        client.auth.get_claims.side_effect = provider_validation_error()

        with (
            patch("auth._get_supabase_client", return_value=client),
            patch("rag.admin_router.SessionLocal") as session_local,
        ):
            response = self.client.get(
                "/admin/knowledge-sources",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Authentication is unavailable"})
        session_local.assert_not_called()

    def test_exact_token_is_passed_once_to_verified_claims_api(self) -> None:
        user_id = uuid4()
        client = Mock()
        client.auth.get_claims.return_value = {"claims": {"sub": str(user_id)}}
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=TOKEN
        )

        with patch("auth._get_supabase_client", return_value=client):
            user = get_authenticated_user(credentials)

        self.assertEqual(user, AuthenticatedUser(id=user_id))
        client.auth.get_claims.assert_called_once_with(TOKEN)

    def test_unexpected_authentication_exception_propagates(self) -> None:
        client = Mock()
        client.auth.get_claims.side_effect = AttributeError("programming error")

        with (
            patch("auth._get_supabase_client", return_value=client),
            patch("rag.admin_router.SessionLocal") as session_local,
        ):
            with self.assertRaisesRegex(AttributeError, "programming error"):
                self.client.get(
                    "/admin/knowledge-sources",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )

        session_local.assert_not_called()

    def test_repeated_factory_calls_reuse_one_trimmed_supabase_client(self) -> None:
        configured = auth_config(
            admin_user_id=uuid4(),
            url="  https://project.supabase.co  ",
            key=SecretStr("  publishable-key  "),
        )

        with (
            patch.dict(sys.modules, {"config": configured}),
            patch("auth.create_client") as create_client,
        ):
            first_client = _get_supabase_client()
            second_client = _get_supabase_client()

        self.assertIs(first_client, create_client.return_value)
        self.assertIs(second_client, first_client)
        create_client.assert_called_once_with(
            "https://project.supabase.co", "publishable-key"
        )

    def test_client_cache_can_be_cleared_between_configurations(self) -> None:
        first_config = auth_config(
            url="https://first.supabase.co", key=SecretStr("first-key")
        )
        second_config = auth_config(
            url="https://second.supabase.co", key=SecretStr("second-key")
        )

        with patch("auth.create_client") as create_client:
            with patch.dict(sys.modules, {"config": first_config}):
                first_client = _get_supabase_client()

            _get_supabase_client.cache_clear()

            with patch.dict(sys.modules, {"config": second_config}):
                second_client = _get_supabase_client()

        self.assertIs(first_client, create_client.return_value)
        self.assertIs(second_client, create_client.return_value)
        self.assertEqual(
            create_client.call_args_list,
            [
                call("https://first.supabase.co", "first-key"),
                call("https://second.supabase.co", "second-key"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
