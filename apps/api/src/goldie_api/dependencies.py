import secrets

from fastapi import Header, HTTPException

from .settings import get_settings


def require_agent_token(x_agent_token: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_agent_token, get_settings().agent_service_token):
        raise HTTPException(status_code=401, detail="Invalid agent token")
