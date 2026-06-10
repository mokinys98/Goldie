import os

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from fastapi.testclient import TestClient

from goldie_api.db import Base, engine
from goldie_api.main import app


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_bot_config_lifecycle() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        created = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "API lifecycle bot", "description": "test", "mode": "SHADOW"},
        )
        assert created.status_code == 201
        bot = created.json()

        versions = client.get(f"/api/v1/bots/{bot['id']}/config-versions", headers=headers).json()
        assert versions[0]["status"] == "DRAFT"

        validated = client.post(
            f"/api/v1/config-versions/{versions[0]['id']}/validate", headers=headers
        )
        assert validated.status_code == 200
        assert validated.json()["status"] == "VALIDATED"

        activated = client.post(
            f"/api/v1/config-versions/{versions[0]['id']}/activate", headers=headers
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "ACTIVE"

        runs = client.get(f"/api/v1/bots/{bot['id']}/runs", headers=headers).json()
        assert len(runs) == 1
        assert runs[0]["status"] == "ACTIVE"


def test_agent_token_is_required() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agents/register",
            json={
                "bot_id": "00000000-0000-0000-0000-000000000000",
                "name": "unauthorized",
                "adapter": "fake",
            },
        )
        assert response.status_code == 401
