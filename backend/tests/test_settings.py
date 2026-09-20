from app.settings import ROOT, load_config, load_feeds


def test_repository_defaults_resolve_without_current_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert (ROOT / "backend/pyproject.toml").is_file()
    assert load_config().refresh_minutes == 15
    assert [item.ticker for item in load_config().seed_watchlist] == ["AAPL", "NVDA", "MSFT"]
    assert len(load_feeds()) == 2
