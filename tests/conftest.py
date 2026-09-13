import os
import tempfile
import pytest
from shadowtalk.data.database import Database


@pytest.fixture(autouse=True)
def test_database(monkeypatch):
    """Use a unique test database for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("shadowtalk.data.database.DB_PATH", path)
    Database._conn = None
    conn = Database.get_connection()
    yield conn
    Database.close()
    for suffix in ["", "-wal", "-shm"]:
        p = path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except PermissionError:
                pass
