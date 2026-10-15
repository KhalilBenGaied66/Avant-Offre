"""Configuration loaded once from config/*.yaml and environment (pydantic-settings).

Every threshold, path, date and model name used by the modules lives here. Modules call
``get_settings()``; they never read YAML or environment variables themselves.

Environment overrides use the ``AVANT_OFFRE_`` prefix and ``__`` for nesting, e.g.
``AVANT_OFFRE_MODE=full`` or ``AVANT_OFFRE_EVAL__T0=2024-07-01``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("AVANT_OFFRE_CONFIG_DIR", PROJECT_ROOT / "config"))

Mode = Literal["sample", "full"]
Retriever = Literal["bm25", "dense"]


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """Load KEY=VALUE lines from .env into os.environ without overriding existing values.

    Kept minimal on purpose (no extra dependency): no interpolation, no multiline values.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


class PathsConfig(BaseModel):
    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")


class HttpConfig(BaseModel):
    timeout_s: float = 60
    retries: int = 5
    user_agent: str = "avant-offre"


class DecpSource(BaseModel):
    dataset_page: str
    parquet_url: str
    schema_url: str
    licence: str


class BoampSource(BaseModel):
    dataset_page: str
    api_base: str
    licence: str
    lookback_days: int = 21
    fields: dict[str, str]
    required_fields: list[str]


class SireneSource(BaseModel):
    api_search_url: str
    api_max_requests_per_s: float = 6
    api_max_lookups: int = 20000
    stock_dataset_page: str
    stock_unite_legale_url: str | None = None
    licence: str


class CpvSource(BaseModel):
    labels_url: str | None = None


class TedSource(BaseModel):
    api_base: str
    enabled: bool = False


class ProbeSource(BaseModel):
    probe_url: str


class SourcesConfig(BaseModel):
    decp: DecpSource
    boamp: BoampSource
    sirene: SireneSource
    cpv: CpvSource
    ted: TedSource
    huggingface: ProbeSource
    anthropic: ProbeSource


class SampleConfig(BaseModel):
    date_from: date
    date_to: date
    departments: list[str]
    cpv_divisions: list[str]


class DedupConfig(BaseModel):
    title_similarity: float = 92


class EntityResolutionConfig(BaseModel):
    fuzzy_threshold: float = 90
    embedding_threshold: float = 0.92
    sample_csv_rows: int = 200


class Bm25Config(BaseModel):
    k1: float = 1.5
    b: float = 0.75


class SearchConfig(BaseModel):
    cpv_group_digits: int = 3
    rrf_k: int = 60
    rerank_top_n: int = 50
    profile_max_wins: int = 50
    profile_strategy: Literal["max", "mean"] = "max"  # mean == centroid for cosine
    retrievers: list[Retriever] = Field(default_factory=lambda: list[Retriever](["bm25"]))
    rerank: bool = False
    bm25: Bm25Config = Field(default_factory=Bm25Config)


class FiltersConfig(BaseModel):
    min_amount_eur: float | None = None
    procedures: list[str] | None = None
    excluded_cpv_divisions: list[str] = Field(default_factory=list)


class IntelConfig(BaseModel):
    k_comparables: int = 100
    tau_days: float = 730
    same_buyer_boost: float = 0.5
    left_censor_months: int = 12
    top_competitors: int = 10
    references_similarity: float = 0.5


class EvalConfig(BaseModel):
    t0: date
    t1: date
    tuning_share: float = 0.2
    n_companies: int = 500
    min_wins_before_t0: int = 5
    min_wins_in_test: int = 1
    sme_only: bool = False
    bootstrap_resamples: int = 1000
    ks: list[int] = Field(default_factory=lambda: [10, 20, 50])
    ndcg_k: int = 20
    embed_tolerance: float = 0.01
    brief_sample_size: int = 50
    brief_review_samples: int = 10


class BriefConfig(BaseModel):
    max_words: int = 250
    max_removed: int = 2


class ApiConfig(BaseModel):
    key_header: str = "X-API-Key"


class Settings(BaseSettings):
    """Merged configuration: config/settings.yaml < environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="AVANT_OFFRE_",
        env_nested_delimiter="__",
        yaml_file=CONFIG_DIR / "settings.yaml",
        extra="ignore",
    )

    mode: Mode = "sample"
    seed: int = 0
    paths: PathsConfig = Field(default_factory=PathsConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    sources: SourcesConfig
    sample: SampleConfig
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    entity_resolution: EntityResolutionConfig = Field(default_factory=EntityResolutionConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    intel: IntelConfig = Field(default_factory=IntelConfig)
    eval: EvalConfig
    brief: BriefConfig = Field(default_factory=BriefConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    # Secrets come from the environment only, never from YAML.
    api_key: str | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, YamlConfigSettingsSource(settings_cls))

    # ---- derived paths -------------------------------------------------------------
    def _abs(self, p: Path) -> Path:
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def data_dir(self) -> Path:
        return self._abs(self.paths.data_dir)

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def vectors_dir(self) -> Path:
        return self.data_dir / "vectors"

    @property
    def traces_dir(self) -> Path:
        return self.data_dir / "traces"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "avant_offre.duckdb"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"

    @property
    def reports_dir(self) -> Path:
        return self._abs(self.paths.reports_dir)


# ---- side configs owned by other teams --------------------------------------------------


class Criterion(BaseModel):
    id: Literal["fit", "references", "incumbent_risk", "openness", "price_realism", "deadline"]
    weight: float
    params: dict[str, float] = Field(default_factory=dict)


class HardStops(BaseModel):
    min_days_to_deadline: int | None = None
    max_amount_eur: float | None = None
    allowed_departments: list[str] | None = None


class Bands(BaseModel):
    go: float
    review: float


class ScorecardConfig(BaseModel):
    hard_stops: HardStops
    criteria: list[Criterion]
    bands: Bands


class TaskModel(BaseModel):
    model: str
    max_tokens: int
    temperature: float = 0.0


class EmbeddingsConfig(BaseModel):
    default: str
    candidates: list[str]
    prefixes: dict[str, dict[str, str]] = Field(default_factory=dict)
    batch_size: int = 64

    def prefix(self, model: str, kind: Literal["query", "passage"]) -> str:
        return self.prefixes.get(model, {}).get(kind, "")


class ModelsConfig(BaseModel):
    gateway: str
    tasks: dict[str, TaskModel]
    alternatives: list[str] = Field(default_factory=list)
    embeddings: EmbeddingsConfig
    reranker: str
    llm_extraction_enabled: bool = True


def _load_yaml(name: str) -> dict[str, Any]:
    with (CONFIG_DIR / name).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{name} must contain a mapping")
    return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings()


@lru_cache(maxsize=1)
def get_scorecard() -> ScorecardConfig:
    return ScorecardConfig.model_validate(_load_yaml("scorecard.yaml"))


@lru_cache(maxsize=1)
def get_models() -> ModelsConfig:
    return ModelsConfig.model_validate(_load_yaml("models.yaml"))


def config_hash() -> str:
    """Short hash of the effective configuration (settings + scorecard + models)."""
    payload = {
        "settings": get_settings().model_dump(mode="json", exclude={"api_key"}),
        "scorecard": get_scorecard().model_dump(mode="json"),
        "models": get_models().model_dump(mode="json"),
    }
    blob = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def reset_caches() -> None:
    """For tests: forget cached configuration."""
    get_settings.cache_clear()
    get_scorecard.cache_clear()
    get_models.cache_clear()
