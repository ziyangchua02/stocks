"""Freeze the local API into static JSON for the GitHub Pages demo.

The demo build serves these files instead of calling the backend, so the
published page needs no server and no API key. Run it with the backend running:

    .venv/bin/python scripts/capture_demo_snapshot.py

Only read endpoints are captured. Nothing here contains credentials: the health
response reports whether a provider is configured, never the key itself.
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend" / "public" / "demo-data"
BASE = "http://127.0.0.1:8000"

# Endpoint -> fixture name. The frontend maps its requests onto these names.
ENDPOINTS = {
    "health": "/api/health",
    "overview": "/api/overview",
    "watchlist": "/api/watchlist",
    "scores": "/api/scores",
    "scoring-config": "/api/scoring/config",
    "news": "/api/news?hours=48&limit=200&include_assessments=true",
    "signals": "/api/signals?limit=200",
    "performance": "/api/performance",
    "alerts": "/api/alerts?unacknowledged_only=false&limit=100",
    "daily-brief": "/api/daily-brief",
}

PER_TICKER = {
    "indicators": "/api/tickers/{ticker}/indicators?include_series=true&limit=400",
    "quote": "/api/tickers/{ticker}/quote",
    "score": "/api/tickers/{ticker}/score",
    "news-analysis": "/api/tickers/{ticker}/news-analysis",
}

FORBIDDEN = ("api_key", "apikey", "x-goog-api-key", "authorization", "secret")


def fetch(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.loads(response.read())


def check_for_credentials(name, payload):
    text = json.dumps(payload).lower()
    for marker in FORBIDDEN:
        if marker in text:
            raise SystemExit(f"Refusing to write {name}: response mentions {marker!r}.")


def write(name, payload):
    check_for_credentials(name, payload)
    path = OUTPUT / f"{name}.json"
    path.write_text(json.dumps(payload, indent=1, sort_keys=False))
    return path


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    try:
        watchlist = fetch("/api/watchlist")
    except (urllib.error.URLError, TimeoutError) as error:
        raise SystemExit(f"Backend is not reachable at {BASE}: {error}") from None
    tickers = [row["ticker"] for row in watchlist["items"]]
    written = []
    for name, path in ENDPOINTS.items():
        written.append(write(name, fetch(path)))
    for ticker in tickers:
        for name, template in PER_TICKER.items():
            written.append(write(f"{name}--{ticker}", fetch(template.format(ticker=ticker))))
    # Per-ticker news, so the feed's ticker filter works offline too.
    for ticker in tickers:
        written.append(
            write(
                f"news--{ticker}",
                fetch(f"/api/news?ticker={ticker}&hours=48&limit=200&include_assessments=true"),
            )
        )
        written.append(write(f"signals--{ticker}", fetch(f"/api/signals?ticker={ticker}&limit=200")))
    manifest = {
        "captured_at": datetime.now(UTC).isoformat(),
        "tickers": tickers,
        "files": sorted(path.name for path in written),
        "note": "Frozen snapshot of a local run. The demo serves these instead of an API.",
    }
    write("manifest", manifest)
    print(f"Wrote {len(written) + 1} files to {OUTPUT.relative_to(ROOT)}")
    print(f"Snapshot time: {manifest['captured_at']}")


if __name__ == "__main__":
    sys.exit(main())
