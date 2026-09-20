from datetime import timedelta

from app.models import Article, iso, utcnow


def test_empty_watchlist_stays_empty_after_restart(store, config):
    store.remove_ticker("AAPL")
    store.initialize(config.seed_watchlist)
    assert store.watchlist() == []


def test_restart_marks_running_refresh_interrupted(store, config):
    store.begin_run("abandoned", "manual", ["AAPL"])
    store.initialize(config.seed_watchlist)
    assert store.run("abandoned")["status"] == "interrupted"


def test_article_dedup_retains_tickers_and_sources(store):
    article = Article(
        title="Apple and Microsoft report earnings",
        publisher="Example",
        url="https://example.com/story?utm_source=feed",
        summary="Summary",
        published_at=utcnow() - timedelta(hours=1),
        fetched_at=utcnow(),
        provider="finnhub",
    ).model_dump(mode="json")
    store.save_articles("AAPL", [article])
    alternate = dict(
        article, url="https://example.com/story?utm_source=rss", provider="rss:Example"
    )
    store.save_articles("MSFT", [alternate])
    syndicated = dict(
        article, url="https://syndication.example.com/story", provider="rss:Syndicated"
    )
    store.save_articles("AAPL", [syndicated])
    result = store.news(iso(utcnow() - timedelta(hours=48)))
    assert result["total"] == 1
    assert result["items"][0]["tickers"] == ["AAPL", "MSFT"]
    assert len(result["items"][0]["sources"]) == 3


def test_older_news_excluded_without_erasing_archive(store):
    article = Article(
        title="Old article",
        publisher="Example",
        url="https://example.com/old",
        published_at=utcnow() - timedelta(hours=49),
        fetched_at=utcnow(),
        provider="finnhub",
    ).model_dump(mode="json")
    store.save_articles("AAPL", [article])
    assert store.news(iso(utcnow() - timedelta(hours=48)))["total"] == 0
    assert store.news(iso(utcnow() - timedelta(hours=72)))["total"] == 1


def test_watchlist_capacity_enforced(store):
    import pytest

    with pytest.raises(ValueError, match="capacity"):
        store.add_ticker("MSFT", "Microsoft", maximum=1)
