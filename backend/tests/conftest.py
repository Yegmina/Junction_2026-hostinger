import pytest

from app import store


@pytest.fixture(autouse=True)
def file_storage(monkeypatch, tmp_path):
    """Every test starts on file storage in its own folder; Aiven tests opt in to real services."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VALKEY_URL", raising=False)
    store.reset()
    store._hits.clear()
    yield
    store.reset()
