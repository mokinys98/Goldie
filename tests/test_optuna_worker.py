import pytest
from goldie_optuna_worker.__main__ import validate_database_configuration


def test_railway_optuna_worker_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "test-environment")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        validate_database_configuration()


def test_railway_optuna_worker_rejects_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "test-environment")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./goldie.db")

    with pytest.raises(RuntimeError, match="requires a PostgreSQL DATABASE_URL"):
        validate_database_configuration()


def test_local_optuna_worker_allows_default_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    validate_database_configuration()
