"""Strict daily-brief output schema. Numbers come from local facts, links from SQLite."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=700)]
PROHIBITED = r"https?://|www\.|guaranteed|can['’]t lose|risk[- ]free|sure thing|will (rise|fall)"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Note(StrictModel):
    ticker: str = Field(min_length=1, max_length=12)
    what_changed: Text
    why: Text
    basis: Literal["news", "market_data", "both"]
    source_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def citations_match_basis(self):
        if self.basis in {"news", "both"} and not self.source_ids:
            raise ValueError("A news-based note must cite at least one supplied article")
        if self.basis == "market_data" and self.source_ids:
            raise ValueError("A market-data note cites the supplied figures, not articles")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("Duplicate citation")
        return self


class BriefResult(StrictModel):
    headline: Text
    overview: Text
    notes: list[Note] = Field(max_length=12)
    watch_items: list[Text] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def language(self):
        texts = [self.headline, self.overview, *self.watch_items]
        texts += [note.what_changed for note in self.notes]
        texts += [note.why for note in self.notes]
        if any(not text.strip() or re.search(PROHIBITED, text, re.I) for text in texts):
            raise ValueError("Invalid or certainty language in the brief")
        return self

    def resolve(self, facts, articles):
        """Attach the local figures and real article links each note relies on."""
        known = {article["id"]: article for article in articles}
        by_ticker = {row["ticker"]: row for row in facts["tickers"]}
        notes = []
        for note in self.notes:
            if note.ticker not in by_ticker:
                raise ValueError("Note refers to a ticker outside the supplied facts")
            if not set(note.source_ids) <= set(known):
                raise ValueError("Unknown citation")
            notes.append(
                note.model_dump()
                | {
                    "figures": by_ticker[note.ticker],
                    "sources": [
                        {
                            key: known[item][key]
                            for key in ("id", "url", "title", "publisher", "published_at")
                        }
                        for item in note.source_ids
                    ],
                }
            )
        covered = {note["ticker"] for note in notes}
        return {
            "headline": self.headline,
            "overview": self.overview,
            "notes": notes,
            "watch_items": self.watch_items,
            "tickers_without_a_note": sorted(set(by_ticker) - covered),
        }
