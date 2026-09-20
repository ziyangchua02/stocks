import math
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None = None) -> str:
    return (value or utcnow()).astimezone(UTC).isoformat()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def symbol(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,4})?", value):
        raise ValueError("Use a US stock ticker such as AAPL or BRK-B.")
    return value


class WatchlistCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    company_name: str = Field(default="", max_length=120)
    _validate_ticker = field_validator("ticker")(symbol)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tickers: list[str] | None = Field(default=None, min_length=1, max_length=50)
    force: bool = False

    @field_validator("tickers")
    @classmethod
    def validate_tickers(cls, values):
        return list(dict.fromkeys(symbol(value) for value in values)) if values else values


class Quote(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    ticker: str
    price: Annotated[float, Field(gt=0)]
    previous_close: Annotated[float | None, Field(gt=0)] = None
    change: float | None = None
    change_percent: float | None = None
    volume: Annotated[int | None, Field(ge=0)] = None
    currency: str | None = None
    source: str
    source_url: str
    source_as_of: datetime
    fetched_at: datetime
    session: str = "regular"
    delay_status: str = "unknown; provider does not guarantee real-time delivery"

    @field_validator("source_as_of", "fetched_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamp requires a timezone")
        if value > utcnow() + timedelta(minutes=5):
            raise ValueError("Quote timestamp is in the future")
        return value.astimezone(UTC)


class Bar(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    ticker: str
    session_date: str
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    adjusted_close: float | None = Field(default=None, gt=0)
    volume: int = Field(ge=0)
    dividends: float | None = None
    stock_splits: float | None = None
    source: str
    source_url: str
    source_as_of: datetime
    timestamp_kind: Literal["session_label"] = "session_label"
    fetched_at: datetime
    is_complete: bool
    adjustment: str


class Article(BaseModel):
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    publisher: str
    summary: str = ""
    published_at: datetime
    fetched_at: datetime
    provider: str
    content_scope: str = "headline_and_excerpt"

    @field_validator("published_at", "fetched_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Article timestamp requires a timezone")
        return value.astimezone(UTC)
