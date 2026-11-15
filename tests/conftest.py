import pytest


@pytest.fixture(autouse=True)
def isolated_rules(tmp_path, monkeypatch):
    """Testerna ska inte påverkas av (eller skriva till) användarens egna regler."""
    monkeypatch.setenv("DUMMYFILLER_RULES", str(tmp_path / "regler.yaml"))
    from dummyfiller import rules
    rules._cache = None
    yield
    rules._cache = None
