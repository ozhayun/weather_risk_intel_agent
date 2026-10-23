import json
from pathlib import Path

from app.config import Settings, load_scoring_config


def test_scoring_weights_sum_to_one():
    cfg = load_scoring_config()
    assert abs(sum(h.weight for h in cfg.hazards.values()) - 1.0) < 1e-9


def test_hurricane_has_no_observed_component():
    assert load_scoring_config().hazards["hurricane"].alpha == 0.0


def test_hubs_json_has_15_hubs_6_midwest():
    hubs = json.loads(Path("data/hubs.json").read_text())
    assert len(hubs) == 15
    assert sum(h["region"] == "midwest" for h in hubs) == 6
    assert {"miami", "houston", "dallas", "denver"} <= {h["hub_id"] for h in hubs}
    assert len({h["hub_id"] for h in hubs}) == 15


def test_settings_default_model(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert Settings(_env_file=None).llm_model == "openai/gpt-4o-mini"


def test_export_env_file_sets_provider_keys_without_overriding(tmp_path, monkeypatch):
    from app.config import export_env_file

    env = tmp_path / ".env"
    env.write_text("WRIA_TEST_KEY=from-file\nWRIA_TEST_KEEP=from-file\n")
    monkeypatch.delenv("WRIA_TEST_KEY", raising=False)
    monkeypatch.setenv("WRIA_TEST_KEEP", "from-shell")
    export_env_file(env)
    import os

    assert os.environ["WRIA_TEST_KEY"] == "from-file"
    assert os.environ["WRIA_TEST_KEEP"] == "from-shell"
    monkeypatch.delenv("WRIA_TEST_KEY")


def test_relative_db_path_resolves_against_repo_root(monkeypatch):
    from app.config import ROOT

    monkeypatch.setenv("DB_PATH", "data/weather.db")
    assert Settings(_env_file=None).db_path == ROOT / "data" / "weather.db"
