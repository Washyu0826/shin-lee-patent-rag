"""Simple JWT auth for POC — username/password login"""
import os
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

SECRET = os.getenv("JWT_SECRET", "change-me-in-production-v3")
ALGORITHM = "HS256"
EXPIRE_HOURS = 24

# Hardcoded users for POC (production: use DB)
USERS = {
    os.getenv("AUTH_USERNAME", "admin"): os.getenv("AUTH_PASSWORD", "patent2026"),
}

security = HTTPBearer(auto_error=False)


def authenticate(username: str, password: str) -> dict | None:
    if username in USERS and USERS[username] == password:
        return {"sub": username, "role": "admin" if username == "admin" else "user"}
    return None


def create_token(data: dict) -> str:
    payload = {**data, "exp": datetime.utcnow() + timedelta(hours=EXPIRE_HOURS)}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")


async def get_current_user(cred: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """FastAPI dependency — returns user info or allows anonymous in POC mode"""
    if cred is None:
        return {"sub": "anonymous", "role": "user"}
    return verify_token(cred.credentials)


async def require_user(user: dict = Depends(get_current_user)) -> dict:
    if user.get("sub") == "anonymous":
        raise HTTPException(401, "Authentication required")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    user = await require_user(user)
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user
