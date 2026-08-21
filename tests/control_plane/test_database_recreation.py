import pytest

from scripts import recreate_control_plane_database as database_recreation
from scripts.recreate_control_plane_database import (
    DATABASE_URL_ENV,
    _database_urls,
    _quoted_database_name,
    main,
)


def test_database_urls_use_asyncpg_and_postgres_for_maintenance() -> None:
    target_url, maintenance_url = _database_urls(
        "postgresql://polybot:secret@localhost:5432/polybot_dev"
    )

    assert target_url.drivername == "postgresql+asyncpg"
    assert target_url.database == "polybot_dev"
    assert maintenance_url.database == "postgres"
    assert maintenance_url.username == target_url.username
    assert maintenance_url.password == target_url.password


@pytest.mark.parametrize(
    "raw_url",
    (
        "sqlite:///polybot.db",
        "postgresql://polybot:secret@localhost",
        "postgresql://polybot:secret@localhost/postgres",
        "postgresql://polybot:secret@localhost/template0",
        "postgresql://polybot:secret@localhost/template1",
    ),
)
def test_database_urls_reject_unsafe_targets(raw_url: str) -> None:
    with pytest.raises(ValueError):
        _database_urls(raw_url)


def test_database_name_is_quoted_as_a_postgres_identifier() -> None:
    assert _quoted_database_name('polybot-"dev') == '"polybot-""dev"'


def test_recreation_requires_an_explicit_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    with pytest.raises(SystemExit, match=DATABASE_URL_ENV):
        main()


def test_main_recreates_before_applying_migrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def recreate(target_url: object, maintenance_url: object) -> None:
        calls.append(("recreate", str(target_url)))
        assert str(maintenance_url).endswith("/postgres")

    def upgrade(target_url: object) -> None:
        calls.append(("upgrade", str(target_url)))

    monkeypatch.setenv(
        DATABASE_URL_ENV,
        "postgresql://polybot:secret@localhost:5432/polybot_dev",
    )
    monkeypatch.setattr(database_recreation, "_recreate_database", recreate)
    monkeypatch.setattr(database_recreation, "_upgrade_to_head", upgrade)

    assert main() == 0
    assert [call[0] for call in calls] == ["recreate", "upgrade"]
