from goldie_api.settings import Settings


def test_railway_postgresql_url_uses_psycopg_driver() -> None:
    settings = Settings(database_url="postgresql://user:password@postgres.railway.internal/db")

    assert settings.database_url == (
        "postgresql+psycopg://user:password@postgres.railway.internal/db"
    )


def test_legacy_postgres_url_uses_psycopg_driver() -> None:
    settings = Settings(database_url="postgres://user:password@localhost/db")

    assert settings.database_url == "postgresql+psycopg://user:password@localhost/db"


def test_existing_sqlalchemy_database_url_is_unchanged() -> None:
    url = "postgresql+psycopg://user:password@localhost/db"

    assert Settings(database_url=url).database_url == url
