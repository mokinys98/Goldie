import uuid
from typing import Any

import requests
from pydantic import BaseModel
from requests import HTTPError

from .settings import AgentSettings


class ApiClient:
    def __init__(self, settings: AgentSettings) -> None:
        self.base_url = settings.api_url.rstrip("/")
        self.headers = {"X-Agent-Token": settings.agent_token}

    def post(self, path: str, payload: BaseModel | dict[str, Any]) -> dict:
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        response = requests.post(
            f"{self.base_url}{path}",
            json=data,
            headers=self.headers,
            timeout=10,
        )
        try:
            response.raise_for_status()
        except HTTPError as exc:
            try:
                body = response.json()
                detail = body.get("detail") or body.get("error", {}).get("message")
            except ValueError:
                detail = response.text.strip()
            message = f"{response.status_code} {response.reason} for {path}"
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeError(message) from exc
        return response.json()

    def register(self, bot_id: uuid.UUID, name: str, adapter: str) -> uuid.UUID:
        result = self.post(
            "/api/v1/agents/register",
            {
                "bot_id": str(bot_id),
                "name": name,
                "adapter": adapter,
                "details": {"read_only": True},
            },
        )
        return uuid.UUID(result["id"])
