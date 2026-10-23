"""Runtime settings (.env) and scoring configuration (config/scoring.toml)."""

import tomllib
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.scoring import ScoringConfig

ROOT = Path(__file__).resolve().parent.parent
SCORING_CONFIG_PATH = ROOT / "config" / "scoring.toml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    llm_model: str = "openai/gpt-4o-mini"
    db_path: Path = ROOT / "data" / "weather.db"
    hubs_path: Path = ROOT / "data" / "hubs.json"
    api_url: str = "http://localhost:8000"


def export_env_file(path: Path) -> None:
    """Provider SDKs read keys from os.environ; real env vars win over the file."""
    load_dotenv(path, override=False)


@lru_cache
def get_settings() -> Settings:
    export_env_file(ROOT / ".env")
    return Settings()


def load_scoring_config(path: Path = SCORING_CONFIG_PATH) -> ScoringConfig:
    return ScoringConfig.model_validate(tomllib.loads(path.read_text()))
