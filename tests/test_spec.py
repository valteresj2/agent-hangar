import pytest

from app import spec


def test_merge_patch_rfc7396():
    target = {"llm": {"connection": "a", "model": "m1", "temperature": 0.2}, "tools": [1, 2]}
    out = spec.merge_patch(target, {"llm": {"connection": "b", "model": None}, "tools": [3]})
    assert out == {"llm": {"connection": "b", "temperature": 0.2}, "tools": [3]}
    assert target["llm"]["model"] == "m1"  # não muta o original


def test_null_removes_whole_field():
    assert spec.merge_patch({"harness": {"id": "codex"}, "x": 1}, {"harness": None}) == {"x": 1}


def test_validate_defaults_and_tool_type():
    out = spec.validate({"tools": [{"name": "t", "url": "https://x"}]})
    assert out["tools"][0]["type"] == "http"
    assert out["llm"]["temperature"] == 0.2


def test_validate_rejects_unknown_fields():
    with pytest.raises(spec.SpecError, match="instrucoes"):
        spec.validate({"instrucoes": "typo"})


def test_harness_and_llm_are_exclusive():
    with pytest.raises(spec.SpecError, match="não os dois"):
        spec.validate({"harness": {"id": "codex"}, "llm": {"connection": "x"}})
    with pytest.raises(spec.SpecError, match="sub_agents"):
        spec.validate({"harness": {"id": "codex"}, "sub_agents": ["a"]})


def test_unknown_harness_and_builtin():
    with pytest.raises(spec.SpecError):
        spec.validate({"harness": {"id": "cursor"}})
    with pytest.raises(spec.SpecError):
        spec.validate({"tools": [{"type": "builtin", "name": "rm_rf"}]})


def test_legacy_llm_keys_are_dropped():
    out = spec.validate({"llm": {"provider": "openai", "base_url": "x", "api_key_env": "K", "model": "m"}})
    assert out["llm"] == {"connection": "", "model": "m", "temperature": 0.2}


def test_json_schema_exposes_fields():
    props = spec.json_schema()["properties"]
    assert {"llm", "harness", "judge", "tests", "sub_agents"} <= set(props)
