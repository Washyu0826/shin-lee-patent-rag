import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import auth_service
import main


class ApiIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_patch = patch.dict(
            auth_service.USERS,
            {"admin": "secret-admin", "alice": "secret-user"},
            clear=True,
        )
        self.user_patch.start()

    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    def tearDown(self):
        self.user_patch.stop()
        main.app.dependency_overrides.clear()

    async def _login(self, username: str, password: str) -> str:
        response = await self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    async def _auth_headers(self, username: str = "admin", password: str = "secret-admin") -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._login(username, password)}"}

    async def test_login_returns_jwt_and_role(self):
        response = await self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret-admin"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("token", payload)
        self.assertEqual(payload["user"]["role"], "admin")

    async def test_protected_patents_requires_auth(self):
        response = await self.client.get("/api/patents")
        self.assertEqual(response.status_code, 401)

    async def test_patents_route_uses_limit_and_returns_payload(self):
        records = [{"doc_number": "TW1", "title": "Optical stack"}]
        with patch.object(main.rag_service, "get_patent_records", return_value=records) as mocked:
            response = await self.client.get(
                "/api/patents?limit=5",
                headers=await self._auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        mocked.assert_called_once_with(limit=5)

    async def test_admin_route_rejects_non_admin_user(self):
        with patch.object(main.rag_service, "get_stats", return_value={"total_chunks": 1}):
            response = await self.client.get(
                "/api/admin/stats",
                headers=await self._auth_headers("alice", "secret-user"),
            )
        self.assertEqual(response.status_code, 403)

    async def test_admin_route_accepts_admin_user(self):
        with patch.object(main.rag_service, "get_stats", return_value={"total_chunks": 7}):
            response = await self.client.get(
                "/api/admin/stats",
                headers=await self._auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_chunks"], 7)

    async def test_feedback_rejects_invalid_payload(self):
        response = await self.client.post(
            "/api/feedback",
            headers=await self._auth_headers(),
            json={"query_log_id": 0, "rating": 0, "comment": "bad"},
        )
        self.assertEqual(response.status_code, 422)

    async def test_feedback_returns_503_when_db_is_unavailable(self):
        with patch.object(main.rag_service, "_db", None):
            response = await self.client.post(
                "/api/feedback",
                headers=await self._auth_headers(),
                json={"query_log_id": 1, "rating": 1, "comment": "helpful"},
            )
        self.assertEqual(response.status_code, 503)

    async def test_feedback_returns_404_for_unknown_query_log(self):
        with patch.object(main.rag_service, "_db", object()), patch.object(main.rag_service, "log_feedback", return_value=False):
            response = await self.client.post(
                "/api/feedback",
                headers=await self._auth_headers(),
                json={"query_log_id": 999, "rating": 1, "comment": "helpful"},
            )
        self.assertEqual(response.status_code, 404)

    async def test_feedback_returns_ok_for_known_query_log(self):
        with patch.object(main.rag_service, "_db", object()), patch.object(main.rag_service, "log_feedback", return_value=True):
            response = await self.client.post(
                "/api/feedback",
                headers=await self._auth_headers(),
                json={"query_log_id": 42, "rating": -1, "comment": "not grounded"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_health_endpoint_is_public_and_can_degrade(self):
        with patch.object(main, "_check", side_effect=[True, False]), patch.object(main.rag_service, "_db", None):
            response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "degraded")
        self.assertFalse(payload["subsystems"]["postgres"])

    async def test_health_strict_returns_503_when_any_dependency_is_down(self):
        with patch.object(main, "_check", side_effect=[False, True]), patch.object(main.rag_service, "_db", object()):
            response = await self.client.get("/api/health/strict")
        self.assertEqual(response.status_code, 503)
