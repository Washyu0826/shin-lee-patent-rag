import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import auth_service


class AuthServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_authenticate_returns_admin_role(self):
        with patch.dict(auth_service.USERS, {"admin": "secret"}, clear=True):
            user = auth_service.authenticate("admin", "secret")
        self.assertEqual(user, {"sub": "admin", "role": "admin"})

    async def test_require_user_rejects_anonymous(self):
        with self.assertRaises(HTTPException) as ctx:
            await auth_service.require_user({"sub": "anonymous", "role": "user"})
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_require_admin_rejects_non_admin(self):
        with self.assertRaises(HTTPException) as ctx:
            await auth_service.require_admin({"sub": "alice", "role": "user"})
        self.assertEqual(ctx.exception.status_code, 403)
