import hashlib
import json
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Environment(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    finnhub_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    telegram_enabled: bool = False  # No Telegram client exists in Phase 1.
    database_path: Path = ROOT / "data" / "research.sqlite3"
    # Set both when the backend is reachable from outside this machine: the token
    # gates /api, and the origins list widens CORS beyond localhost. Empty means
    # local-only, which is the default the rest of the project assumes.
    api_token: SecretStr = SecretStr("")
    allowed_origins: str = ""

    @property
    def origins(self) -> list[str]:
        parts = (part.strip().rstrip("/") for part in self.allowed_origins.split(","))
        return [part for part in parts if part]


class Seed(BaseModel):
    ticker: str
    company_name: str = ""


class Index(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=r"^\^?[A-Z][A-Z0-9.\-]{0,9}$")
    name: str = Field(min_length=1, max_length=60)


class CacheDurations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote: int = Field(default=900, ge=60)
    history: int = Field(default=3600, ge=60)
    fundamentals: int = Field(default=86400, ge=60)
    news: int = Field(default=900, ge=60)
    rss: int = Field(default=900, ge=60)


class NewsAnalysisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    model: str = Field(default="gemini-3.1-flash-lite", pattern=r"^gemini-[a-z0-9.-]+$")
    max_articles: int = Field(default=12, ge=1, le=30)
    max_excerpt_chars: int = Field(default=1200, ge=200, le=4000)
    max_output_tokens: int = Field(default=6000, ge=1000, le=16000)
    timeout_seconds: float = Field(default=45, ge=5, le=120)
    retry_attempts: int = Field(default=2, ge=1, le=3)
    min_interval_seconds: float = Field(default=6, ge=0, le=60)
    max_calls_per_day: int = Field(default=100, ge=1, le=1000)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_minutes: int = Field(default=15, ge=1, le=60)
    scheduler_enabled: bool = True
    refresh_on_startup: bool = False
    market_calendar: str = "NYSE"
    market_timezone: str = "America/New_York"
    history_period: str = "2y"
    news_lookback_hours: int = Field(default=48, ge=1, le=168)
    max_watchlist_size: int = Field(default=50, ge=1, le=100)
    market_indices: list[Index] = Field(default_factory=list, max_length=8)
    request_timeout_seconds: float = Field(default=15, gt=0, le=60)
    retry_attempts: int = Field(default=3, ge=1, le=5)
    finnhub_requests_per_minute: int = Field(default=50, ge=1, le=60)
    cache_seconds: CacheDurations = Field(default_factory=CacheDurations)
    news_analysis: NewsAnalysisConfig = Field(default_factory=NewsAnalysisConfig)
    seed_watchlist: list[Seed] = Field(default_factory=list)

    @field_validator("refresh_minutes")
    @classmethod
    def even_intervals(cls, value):
        if 60 % value:
            raise ValueError("refresh_minutes must divide 60 evenly")
        return value


class Feed(BaseModel):
    name: str
    url: str = Field(pattern=r"^https://")


Point = Annotated[list[float], Field(min_length=2, max_length=2)]


class Curve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weight: float = Field(default=1.0, gt=0)
    curve: list[Point] = Field(min_length=2)

    @field_validator("curve")
    @classmethod
    def ascending(cls, points):
        xs = [x for x, _ in points]
        if xs != sorted(xs) or len(set(xs)) != len(xs):
            raise ValueError("Curve inputs must be strictly ascending")
        if any(not 0 <= y <= 100 for _, y in points):
            raise ValueError("Curve sub-scores must be between 0 and 100")
        return points


class CurveComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    curves: dict[str, Curve] = Field(min_length=1)


class TrendComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_conditions: int = Field(default=2, ge=1)
    conditions: dict[str, float] = Field(min_length=1)


class NewsComponent(CurveComponent):
    max_age_hours: float = Field(default=48, gt=0)
    impact_scaling: dict[str, float] = Field(default_factory=dict)

    @field_validator("impact_scaling")
    @classmethod
    def impacts(cls, scaling):
        if set(scaling) != {"low", "medium", "high"} or any(
            not 0 <= v <= 1 for v in scaling.values()
        ):
            raise ValueError("impact_scaling needs low/medium/high factors between 0 and 1")
        return scaling


class Components(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trend: TrendComponent
    momentum: CurveComponent
    volume: CurveComponent
    range_position: CurveComponent
    valuation: CurveComponent
    growth_quality: CurveComponent
    news_sentiment: NewsComponent


class Labels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strong_setup: float = Field(default=70, ge=0, le=100)
    watch: float = Field(default=58, ge=0, le=100)
    neutral: float = Field(default=42, ge=0, le=100)

    @model_validator(mode="after")
    def ordered(self):
        if not self.strong_setup > self.watch > self.neutral:
            raise ValueError("Label thresholds must decrease: strong_setup > watch > neutral")
        return self


class Caution(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    downgrade: bool = False


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[a-z0-9-]+$")
    min_weight_coverage: float = Field(default=0.5, gt=0, le=1)
    weights: dict[str, float]
    labels: Labels = Field(default_factory=Labels)
    components: Components
    cautions: dict[str, Caution] = Field(default_factory=dict)

    @model_validator(mode="after")
    def weights_match_components(self):
        names = set(type(self.components).model_fields)
        if set(self.weights) != names:
            raise ValueError(f"weights must cover exactly: {', '.join(sorted(names))}")
        if any(value < 0 for value in self.weights.values()):
            raise ValueError("Weights cannot be negative")
        if sum(self.weights.values()) <= 0:
            raise ValueError("At least one weight must be positive")
        return self

    def fingerprint(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, allow_nan=False)
        return hashlib.sha256(payload.encode()).hexdigest()


class AlertRule(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True


class BriefConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    lookback_hours: float = Field(default=24, ge=1, le=168)
    max_articles: int = Field(default=10, ge=1, le=30)
    max_output_tokens: int = Field(default=4000, ge=1000, le=16000)


class AlertsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    rules: dict[str, AlertRule] = Field(default_factory=dict)
    brief: BriefConfig = Field(default_factory=BriefConfig)

    @field_validator("rules")
    @classmethod
    def known_rules(cls, rules):
        known = {
            "score_threshold",
            "score_change",
            "label_change",
            "price_move",
            "high_impact_news",
        }
        unknown = set(rules) - known
        if unknown:
            raise ValueError(f"Unknown alert rule(s): {', '.join(sorted(unknown))}")
        return rules

    def rule(self, name):
        found = self.rules.get(name)
        return found if found and found.enabled and self.enabled else None


def load_config() -> Config:
    return Config.model_validate(yaml.safe_load((ROOT / "config/settings.yaml").read_text()))


def load_alerts() -> AlertsConfig:
    return AlertsConfig.model_validate(yaml.safe_load((ROOT / "config/alerts.yaml").read_text()))


def load_scoring() -> ScoringConfig:
    return ScoringConfig.model_validate(yaml.safe_load((ROOT / "config/scoring.yaml").read_text()))


def load_feeds() -> list[Feed]:
    data = yaml.safe_load((ROOT / "config/feeds.yaml").read_text())
    return [Feed.model_validate(item) for item in data.get("feeds", [])]
