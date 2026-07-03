"""HTTP Basic auth for the whole app.

If APP_USERNAME and APP_PASSWORD are unset, auth is disabled (local dev).
On deploy, set both — otherwise anyone with the URL burns your API keys.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

log = logging.getLogger(__name__)
_security = HTTPBasic(auto_error=False)

if not settings.app_password:
    log.warning("APP_PASSWORD is unset — auth is DISABLED. Do not deploy like this.")


def require_auth(creds: HTTPBasicCredentials | None = Depends(_security)) -> None:
    if not settings.app_password:
        return
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    user_ok = secrets.compare_digest(creds.username, settings.app_username)
    pass_ok = secrets.compare_digest(creds.password, settings.app_password)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
