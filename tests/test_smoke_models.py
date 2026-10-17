from pathlib import Path

import pytest

pytest.importorskip("PIL.Image")

from scripts import smoke_models as smoke  # noqa: E402


def test_default_model_settings_match_baseline(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=test-key\n", encoding="utf-8")
    env = smoke.load_env(env_file)
    settings = smoke.resolve_settings(env)
    assert settings["decision_model"] == "perplexity/pplx-decider-v1.2"
    assert settings["extraction_model"] == "anthropic/claude-haiku-5.5"
    assert settings["escalation_model"] == "google/gemini-4-argon"
    assert settings["base_url"] == "https://openrouter.ai/api"


def test_env_example_declares_baseline_models():
    env_example = Path(smoke.ROOT / ".env.example")
    assert env_example.exists()
    parsed = smoke.load_env(env_example)
    assert parsed["AI_IDP_DECISION_MODEL"] == "perplexity/pplx-decider-v1.2"
    assert parsed["AI_IDP_EXTRACTION_MODEL"] == "anthropic/claude-haiku-5.5"
    assert parsed["AI_IDP_ESCALATION_MODEL"] == "google/gemini-4-argon"


def test_payload_builders_include_image_and_schema():
    data_url = smoke.make_test_image_data_url()
    assert data_url.startswith("data:image/png;base64,")

    dec = smoke.build_decision_payload("perplexity/pplx-decider-v1.2", data_url)
    assert dec["model"] == "perplexity/pplx-decider-v1.2"
    assert set(dec["questions"]) == {"has_total_amount", "modality", "verification"}

    ext = smoke.build_extraction_payload("anthropic/claude-haiku-5.5", data_url)
    assert ext["model"] == "anthropic/claude-haiku-5.5"
    assert ext["response_format"]["type"] == "json_schema"
    assert ext["response_format"]["json_schema"]["strict"] is True
