import pytest


@pytest.fixture
def write(tmp_path):
    def _write(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return str(p)

    return _write
