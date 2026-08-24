"""Unit tests for llama_ai.py.

Run under the gguf venv python (`make test-unit`). These are hermetic:
they do NOT launch llama-server or require installed ~/bin artifacts — they
exercise the pure functions in llama_ai.py and the on-disk model scan.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

import llama_ai


def _minimal_gguf(tmp_path: Path) -> Path:
    """Write a tiny but well-formed GGUF header so the fast reader parses it.

    Builds: general.architecture (str), general.name (str), block_count,
    embedding_length, attention.head_count, attention.head_count_kv,
    context_length (all uint32), tokenizer.chat_template (str).
    """
    p = tmp_path / "mini.gguf"

    def s(v: str) -> bytes:
        b = v.encode("utf-8")
        return struct.pack("<Q", len(b)) + b

    def kv(key: str, vtype: int, val: bytes) -> bytes:
        return struct.pack("<Q", len(key)) + key.encode() + struct.pack("<I", vtype) + val

    buf = bytearray()
    buf += b"GGUF"
    buf += struct.pack("<I", 3)          # version
    buf += struct.pack("<Q", 0)          # tensor_count
    pairs = [
        kv("general.architecture", 8, s("qwen2")),
        kv("general.name", 8, s("mini-model")),
        kv("qwen2.block_count", 4, struct.pack("<I", 28)),
        kv("qwen2.embedding_length", 4, struct.pack("<I", 3584)),
        kv("qwen2.attention.head_count", 4, struct.pack("<I", 28)),
        kv("qwen2.attention.head_count_kv", 4, struct.pack("<I", 4)),
        kv("qwen2.context_length", 4, struct.pack("<I", 32768)),
        kv("tokenizer.chat_template", 8, s("<|im_start|>template<|im_end|>")),
    ]
    buf += struct.pack("<Q", len(pairs))
    for x in pairs:
        buf += x
    p.write_bytes(bytes(buf))
    return p


# ---------------------------------------------------------------------------
# metadata reader
# ---------------------------------------------------------------------------
def test_fast_reader_parses_minimal_gguf(tmp_path):
    p = _minimal_gguf(tmp_path)
    m = llama_ai.read_model_meta_fast(str(p))
    assert m is not None
    assert m["arch"] == "qwen2"
    assert m["name"] == "mini-model"
    assert m["n_layer"] == 28
    assert m["n_embd"] == 3584
    assert m["n_head"] == 28
    assert m["n_head_kv"] == 4
    assert m["ctx_train"] == 32768
    assert "template" in m["chat_template"]


def test_fast_reader_returns_none_on_non_gguf(tmp_path):
    p = tmp_path / "junk.bin"
    p.write_bytes(b"NOTAGGUFFILE" * 16)
    assert llama_ai.read_model_meta_fast(str(p)) is None


# ---------------------------------------------------------------------------
# model scan (reads whatever lives under ~/models)
# ---------------------------------------------------------------------------
def test_models_root_exists(models_root):
    # The python script hardcodes MODELS_ROOT = ~/models; it MUST exist on the
    # host for the launcher to find any model.
    assert llama_ai.MODELS_ROOT == str(models_root)
    assert models_root.is_dir(), (
        "~/models does not exist on this host; create it to use llama-ai"
    )


@pytest.mark.skipif(not Path(llama_ai.MODELS_ROOT).is_dir(), reason="no ~/models dir")
def test_scan_models_returns_sorted_list():
    models = llama_ai.scan_models()
    assert models, "no .gguf found under ~/models"
    for m in models:
        for key in ("file", "name", "arch", "size_gb", "ctx_train"):
            assert key in m, f"meta missing key {key}"
    sizes = [m["size_gb"] for m in models]
    assert sizes == sorted(sizes, reverse=True), "models not sorted by size desc"


# ---------------------------------------------------------------------------
# reasoning detection
# ---------------------------------------------------------------------------
def test_is_reasoning_model_detects_markers():
    assert llama_ai.is_reasoning_model({"chat_template": "x<|start_of_fim|>y"})
    assert llama_ai.is_reasoning_model({"chat_template": "deepseek reasoning cot"})
    assert not llama_ai.is_reasoning_model({"chat_template": "llama3 meta"})
    assert not llama_ai.is_reasoning_model({"chat_template": ""})


# ---------------------------------------------------------------------------
# auto-tuning math
# ---------------------------------------------------------------------------
def test_kv_bytes_per_token_positive():
    meta = {"n_embd": 3584, "n_head": 28, "n_head_kv": 4, "n_layer": 28}
    assert llama_ai.kv_bytes_per_token(meta) > 0
    # q4_0 (default) is ~4x smaller than fp16
    assert llama_ai.kv_bytes_per_token(meta, "q4_0") < llama_ai.kv_bytes_per_token(meta, "f16")


def test_tuned_context_capped_by_train_ctx():
    meta = {
        "ctx_train": 4096, "n_embd": 3584, "n_head": 28,
        "n_head_kv": 4, "n_layer": 28,
    }
    # tiny budget => kv/token is positive and 1/that -> tiny ctx, floored at 2048
    assert llama_ai.kv_bytes_per_token(meta) > 0
    ctx = llama_ai.tuned_context(meta, 1)
    assert ctx == 2048
    # huge budget => capped at train ctx (and rounded to a 1024 multiple)
    ctx2 = llama_ai.tuned_context(meta, 10 ** 18)
    assert ctx2 <= 4096
    assert ctx2 % 1024 == 0


# ---------------------------------------------------------------------------
# command construction
# ---------------------------------------------------------------------------
@pytest.fixture
def server_on_path(monkeypatch):
    """Force llama_ai to believe a llama-server exists at a fake path."""
    fake = "/usr/local/bin/llama-server"
    monkeypatch.setenv("LLAMA_SERVER", fake)
    monkeypatch.setattr(llama_ai, "LLAMA_SERVER", fake, raising=False)


def test_build_command_has_core_flags(server_on_path):
    meta = {
        "file": "/models/x.gguf", "name": "x", "arch": "qwen2",
        "n_layer": 28, "n_embd": 3584, "n_head": 28, "n_head_kv": 4,
        "ctx_train": 32768,
        "chat_template": "llama3",   # non-reasoning
        "size_gb": 24.0,
    }
    cmd = llama_ai.build_command(meta, ctx=4096, port=11434)
    joined = " ".join(cmd)
    assert cmd[0] == "/usr/local/bin/llama-server"
    assert "-m" in cmd and str(meta["file"]) in cmd
    assert "--host" in cmd and "0.0.0.0" in cmd
    assert "--port" in cmd and "11434" in cmd
    assert "-c" in cmd and "4096" in cmd
    assert "-ngl" in cmd and "99" in cmd
    assert "--alias" in cmd and "llm-local" in cmd
    assert "--jinja" in cmd
    # big model => 1 parallel slot
    assert joined.endswith("-np 1") or "-np 1" in joined
    # non-reasoning => no --reasoning
    assert "--reasoning" not in cmd


def test_build_command_reasoning_and_slots(server_on_path):
    meta = {
        "file": "/models/y.gguf", "name": "y", "arch": "deepseek",
        "n_layer": 28, "n_embd": 3584, "n_head": 28, "n_head_kv": 4,
        "ctx_train": 32768,
        "chat_template": "deepseek cot",  # reasoning
        "size_gb": 4.0,                   # small => 2 slots
    }
    cmd = llama_ai.build_command(meta, ctx=4096, port=11434)
    assert "--reasoning" in cmd and "on" in cmd
    assert "--reasoning-format" in cmd and "deepseek" in cmd
    assert "-np" in cmd and "2" in cmd


# ---------------------------------------------------------------------------
# llama-server resolution
# ---------------------------------------------------------------------------
def test_resolve_from_env(monkeypatch, tmp_path):
    fake_a = tmp_path / "fake-server-a"
    fake_a.write_bytes(b"binary")
    fake_a.chmod(0o755)
    monkeypatch.setenv("LLAMA_SERVER", str(fake_a))
    assert llama_ai.resolve_llama_server() == str(fake_a)


def test_resolve_from_path(monkeypatch, tmp_path):
    monkeypatch.delenv("LLAMA_SERVER", raising=False)
    fake = tmp_path / "llama-server"
    fake.write_bytes(b"binary")
    fake.chmod(0o755)
    monkeypatch.setattr(llama_ai.shutil, "which", lambda _: str(fake))
    assert llama_ai.resolve_llama_server() == str(fake)


def test_resolve_missing_raises_systemexit(monkeypatch, tmp_path):
    monkeypatch.delenv("LLAMA_SERVER", raising=False)
    monkeypatch.setattr(llama_ai.shutil, "which", lambda _: None)
    # Redirect the ~/bin/llama-server fallback to an empty tmp dir so the
    # "missing" path is genuinely exercised even on hosts with make-installed
    # ~/bin/llama-server symlinks.
    empty = tmp_path / "fakehome"
    empty.mkdir()
    monkeypatch.setattr(llama_ai.os.path, "expanduser", lambda _: str(empty))
    with pytest.raises(SystemExit) as e:
        llama_ai.resolve_llama_server()
    assert e.value.code != 0
    assert "llama-server" in str(e.value)


def test_resolve_falls_back_to_home_bin(monkeypatch, tmp_path):
    monkeypatch.delenv("LLAMA_SERVER", raising=False)
    monkeypatch.setattr(llama_ai.shutil, "which", lambda _: None)
    home = tmp_path / "fakehome"
    srv = home / "bin" / "llama-server"
    srv.parent.mkdir(parents=True)
    srv.write_bytes(b"binary")
    srv.chmod(0o755)
    monkeypatch.setattr(llama_ai.os.path, "expanduser", lambda _: str(home))
    assert llama_ai.resolve_llama_server() == str(srv)


def test_resolve_bad_env_raises_systemexit(monkeypatch, tmp_path):
    monkeypatch.setenv("LLAMA_SERVER", str(tmp_path / "does-not-exist"))
    with pytest.raises(SystemExit):
        llama_ai.resolve_llama_server()
