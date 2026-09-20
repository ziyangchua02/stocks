"""Strict output schema; links always come from SQLite, never from the model."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=900)]
SourceIds = Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=30)]
Sentiment = Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
Impact = Literal["low", "medium", "high"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Reason(StrictModel):
    text: Text
    source_ids: SourceIds


class Evidence(StrictModel):
    summary: SourceIds
    sentiment: Reason
    impact: Reason
    time_horizon: Reason
    key_points: list[SourceIds] = Field(max_length=5)
    risks: list[SourceIds] = Field(max_length=5)


class ArticleAssessment(StrictModel):
    article_id: int = Field(gt=0)
    sentiment: Sentiment
    impact: Impact
    rationale: Text


class NewsResult(StrictModel):
    summary: Text
    sentiment: Sentiment
    impact: Impact
    time_horizon: Literal["short", "medium", "long"]
    key_points: list[Text] = Field(max_length=5)
    risks: list[Text] = Field(max_length=5)
    evidence: Evidence
    article_assessments: list[ArticleAssessment] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def validate_claims(self):
        if len(self.key_points) != len(self.evidence.key_points):
            raise ValueError("Each key point needs matching evidence")
        if len(self.risks) != len(self.evidence.risks):
            raise ValueError("Each risk needs matching evidence")
        texts = [self.summary, *self.key_points, *self.risks]
        texts += [
            getattr(self.evidence, field).text for field in ("sentiment", "impact", "time_horizon")
        ]
        texts += [item.rationale for item in self.article_assessments]
        prohibited = (
            r"https?://|www\.|guaranteed|can['’]t lose|risk[- ]free|sure thing|will (rise|fall)"
        )
        if any(not text.strip() or re.search(prohibited, text, re.I) for text in texts):
            raise ValueError("Invalid or certainty language in a claim")
        return self

    def resolve(self, articles):
        known = {article["id"]: article for article in articles}
        assessed = [item.article_id for item in self.article_assessments]
        if len(assessed) != len(set(assessed)) or set(assessed) != set(known):
            raise ValueError("Article assessments must cover exactly the supplied sources")

        def sources(ids):
            if len(ids) != len(set(ids)) or not set(ids) <= set(known):
                raise ValueError("Unknown or duplicate citation")
            return [
                {
                    key: known[item][key]
                    for key in ("id", "url", "title", "publisher", "published_at", "fetched_at")
                }
                for item in ids
            ]

        def claim(text, ids):
            return {"text": text, "sources": sources(ids)}

        claims = {"summary": claim(self.summary, self.evidence.summary)}
        for field in ("key_points", "risks"):
            claims[field] = [
                claim(text, ids)
                for text, ids in zip(
                    getattr(self, field), getattr(self.evidence, field), strict=True
                )
            ]
        for field in ("sentiment", "impact", "time_horizon"):
            reason = getattr(self.evidence, field)
            claims[field] = claim(reason.text, reason.source_ids)
        result = self.model_dump(exclude={"evidence", "article_assessments"})
        result["claims"] = claims
        result["article_assessments"] = [
            item.model_dump() | {"sources": sources([item.article_id])}
            for item in self.article_assessments
        ]
        return result
