import pytest

from app import crypto
from app import services as svc
from app.models import LlmConnection


def test_encrypt_roundtrip_and_legacy_passthrough():
    enc = crypto.encrypt("sk-secret")
    assert enc.startswith("enc:v1:") and "sk-secret" not in enc
    assert crypto.decrypt(enc) == "sk-secret"
    assert crypto.encrypt(enc) == enc  # idempotente
    assert crypto.decrypt("plain-legacy") == "plain-legacy"


def test_connection_key_encrypted_at_rest_and_masked(db, uniq):
    name = uniq("conn")
    svc.upsert_llm_connection(db, name, "https://llm.example/v1", "m", "sk-abcdef1234", "", "t", "openai", 1.0, 2.0)
    row = db.query(LlmConnection).filter_by(name=name).one()
    assert crypto.is_encrypted(row.api_key)
    d = svc.llm_connection_dict(row)
    assert "sk-abcdef1234" not in str(d)
    assert d["api_key"].endswith("1234")


def test_edit_without_key_keeps_previous(db, uniq):
    name = uniq("conn")
    svc.upsert_llm_connection(db, name, "https://llm.example/v1", "m", "sk-keep-9999", "", "t", "openai")
    svc.upsert_llm_connection(db, name, "https://llm.example/v2", "m2", "", "", "t", "openai")
    row = db.query(LlmConnection).filter_by(name=name).one()
    assert crypto.decrypt(row.api_key) == "sk-keep-9999" and row.base_url.endswith("/v2")


def test_protocol_validation(db, uniq):
    with pytest.raises(svc.PlatformError):
        svc.upsert_llm_connection(db, uniq("c"), "https://x/v1", "m", "k", "", "t", "grpc")


def test_cost():
    assert svc.cost_usd(1_000_000, 500_000, (0.5, 2.0)) == 1.5
    assert svc.cost_usd(10, 10, (None, None)) == 0


def test_mcp_url_must_be_http(db, uniq):
    with pytest.raises(svc.PlatformError):
        svc.upsert_mcp(db, uniq("mcp"), "file:///etc/passwd")
