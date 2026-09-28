import sys
import unittest
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from main import app


class CorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_allows_vite_origin_with_requested_policy(self) -> None:
        origin = "http://localhost:5173"
        response = self.client.options(
            "/questions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, Authorization",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], origin)
        self.assertEqual(response.headers["access-control-allow-methods"], "GET, POST")
        self.assertIn(
            "content-type", response.headers["access-control-allow-headers"].lower()
        )
        self.assertIn(
            "authorization", response.headers["access-control-allow-headers"].lower()
        )
        self.assertNotIn("access-control-allow-credentials", response.headers)

    def test_does_not_allow_unknown_origin(self) -> None:
        response = self.client.options(
            "/questions",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )

        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
