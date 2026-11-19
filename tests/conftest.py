import pytest

from devtrack.core import Core, find_core_binary
from devtrack.store import Repository

BACKENDS = ["python"] + (["cpp"] if find_core_binary() else [])


@pytest.fixture(params=BACKENDS)
def core(request):
    return Core(find_core_binary() if request.param == "cpp" else None)


@pytest.fixture
def repo(tmp_path, core):
    r = Repository.init(tmp_path)
    r.core = core
    yield r
    r.close()


@pytest.fixture
def write(tmp_path):
    def _write(name: str, text: str):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p
    return _write
