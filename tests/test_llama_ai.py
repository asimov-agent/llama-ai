"""Unit tests for scripts/llama_serve.py (the GGUF launcher).

Run under the gguf venv python (`make test-unit`). These are hermetic:
they do NOT launch llama-server or require installed ~/bin artifacts — they
exercise the pure functions in scripts/llama_serve.py and the on-disk model scan.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

import scripts.llama_serve as llama_ai  # noqa: E402  (relocated from root llama_ai.py; importable: gguf+numpy come from the venv)


def _minimal_gguf(tmp_path: Path, filename: str = "mini.gguf") -> Path:
    """Write a tiny but well-formed GGUF header so the fast reader parses it.

    Builds: general.architecture (str), general.name (str), block_count,
    embedding_length, attention.head_count, attention.head_count_kv,
    context_length (all uint32), tokenizer.chat_template (str).
    """
    p = tmp_path / filename

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
# model scan (reads whatever lives under MODELS_ROOT)
# ---------------------------------------------------------------------------
@pytest.fixture
def hermetic_models_dir(tmp_path, monkeypatch):
    """Seed a temp models dir with two mini GGUFs of different sizes and point
    llama_ai.MODELS_ROOT at it, so the scan tests run hermetically — no host
    ~/models dependency, no skips."""
    models = tmp_path / "models"
    models.mkdir()
    _minimal_gguf(models, "a-small.gguf")                      # tiny header
    big = _minimal_gguf(models, "z-big.gguf")                  # larger file
    big.write_bytes(big.read_bytes() + b"\x00" * (2048 * 1024))  # ~2 MB
    monkeypatch.setattr(llama_ai, "MODELS_ROOT", str(models))
    return models


def test_models_root_exists(hermetic_models_dir):
    # MODELS_ROOT points at a real, existing seeded dir — no host dependency.
    assert llama_ai.MODELS_ROOT == str(hermetic_models_dir)
    assert Path(llama_ai.MODELS_ROOT).is_dir(), (
        "MODELS_ROOT points at a dir that does not exist"
    )


def test_scan_models_returns_sorted_list(hermetic_models_dir):
    models = llama_ai.scan_models()
    assert len(models) == 2, "expected the two seeded ggu files to be scanned"
    for m in models:
        for key in ("file", "name", "arch", "size_gb", "ctx_train"):
            assert key in m, f"meta missing key {key}"
    sizes = [m["size_gb"] for m in models]
    assert sizes == sorted(sizes, reverse=True), "models not sorted by size desc"
    # the bigger (padded z-big.gguf) must sort first
    assert models[0]["size_gb"] > models[1]["size_gb"]
    assert models[0]["file"].endswith("z-big.gguf")


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
# author-recommended sampling defaults (general.sampling.*)
# ---------------------------------------------------------------------------
def test_build_command_uses_model_sampling_when_present(server_on_path):
    """Model-supplied sampling emits model-specific flags (separate argv elems)."""
    meta = {
        "file": "/models/s.gguf", "name": "s", "arch": "qwen2",
        "n_layer": 28, "n_embd": 3584, "n_head": 28, "n_head_kv": 4,
        "ctx_train": 32768, "chat_template": "llama3", "size_gb": 24.0,
        "sampling": {"temperature": "0.7", "top_p": "0.95"},
    }
    cmd = llama_ai.build_command(meta, ctx=4096, port=11434)
    assert "--temp" in cmd and "0.7" in cmd
    assert "--top-p" in cmd and "0.95" in cmd
    # the preset's values must NOT also appear (no double flags)
    assert "0.6" not in cmd
    assert "0.9" not in cmd
    # flag and value adjacent (separate argv elements, not "--temp 0.7")
    assert cmd[cmd.index("--temp") + 1] == "0.7"
    assert cmd[cmd.index("--top-p") + 1] == "0.95"


def test_build_command_falls_back_to_preset_when_no_sampling(server_on_path):
    """No sampling metadata => emit the global SAMPLING preset (unchanged)."""
    meta = {
        "file": "/models/p.gguf", "name": "p", "arch": "qwen2",
        "n_layer": 28, "n_embd": 3584, "n_head": 28, "n_head_kv": 4,
        "ctx_train": 32768, "chat_template": "general", "size_gb": 24.0,
        "sampling": {},
    }
    cmd = llama_ai.build_command(meta, ctx=4096, port=11434)
    joined = " ".join(cmd)
    assert "--temp 0.6" in joined
    assert "--top-p 0.9" in joined
    assert "--top-k 40" in joined
    assert "--min-p 0.05" in joined
    assert "--repeat-penalty 1.05" in joined


def test_sampling_flag_map_covers_all_keys(server_on_path):
    meta = {
        "file": "/models/a.gguf", "name": "a", "arch": "qwen2",
        "n_layer": 28, "n_embd": 3584, "n_head": 28, "n_head_kv": 4,
        "ctx_train": 32768, "chat_template": "llama", "size_gb": 24.0,
        "sampling": {
            "temperature": "0.7", "top_p": "0.9", "top_k": "40",
            "min_p": "0.05", "repeat_penalty": "1.1",
        },
    }
    cmd = llama_ai.build_command(meta, ctx=4096, port=11434)
    for flag in ("--temp", "--top-p", "--top-k", "--min-p", "--repeat-penalty"):
        assert flag in cmd, f"missing {flag}"


def test_build_command_skips_unknown_sampling_key_no_keyerror(server_on_path):
    """An unrecognised sampling key must be ignored, never raise KeyError."""
    meta = {
        "file": "/models/u.gguf", "name": "u", "arch": "qwen2",
        "n_layer": 28, "n_embd": 3584, "n_head": 28, "n_head_kv": 4,
        "ctx_train": 32768, "chat_template": "llama", "size_gb": 24.0,
        "sampling": {"temperature": "0.7", "nonsense_key": "9.9"},
    }
    cmd = llama_ai.build_command(meta, ctx=4096, port=11434)
    assert "--temp" in cmd and "0.7" in cmd
    assert "nonsense_key" not in cmd
    assert "--nonsense-key" not in cmd


def test_extract_sampling_from_kv_picks_present_fields():
    kv = {
        "general.architecture": "qwen2",
        "general.sampling.temperature": 0.7,
        "general.sampling.top_p": 0.95,
    }
    out = llama_ai._extract_sampling_from_kv(kv)
    assert out == {"temperature": "0.7", "top_p": "0.95"}
    # absent keys omitted; never raises
    assert llama_ai._extract_sampling_from_kv({"general.architecture": "qwen2"}) == {}


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


# ---------------------------------------------------------------------------
# top-tier discovery: min_trending_score rating floor
# ---------------------------------------------------------------------------
def test_discover_top_tier_min_trending_score_filters(monkeypatch):
    """discover_top_tier must drop repos below the rating floor."""
    repos = [
        {"repo": "unsloth/Qwen3.8-27B-GGUF", "downloads": 1, "likes": 1, "trendingScore": 300},
        {"repo": "orcarouter/Qwen3.8-27B-Uncensored-GGUF", "downloads": 1, "likes": 1,
         "trendingScore": 120},
    ]

    def fake_trending(limit=25):
        return repos

    def fake_files(repo):
        return [{"path": f"{repo.split('/')[-1]}-Q8_0.gguf", "size_bytes": 5 * 1024 ** 3,
                 "size_gb": 5.0}]

    monkeypatch.setattr(llama_ai, "_trending_gguf_repos", fake_trending)
    monkeypatch.setattr(llama_ai, "_repo_gguf_files", fake_files)
    monkeypatch.setattr(llama_ai, "MIN_TOP_TIER_GB", 1.0)

    # no floor -> both fit and are returned, sorted by size (tie -> trend desc)
    all = llama_ai.discover_top_tier(limit=5, total_ram_bytes=48 * 1024 ** 3,
                                     headroom_bytes=3 * 1024 ** 3, min_trending_score=0)
    assert len(all) == 2

    # floor 200 -> only the 300-rated repo survives
    rated = llama_ai.discover_top_tier(limit=5, total_ram_bytes=48 * 1024 ** 3,
                                       headroom_bytes=3 * 1024 ** 3, min_trending_score=200)
    assert [c["repo"] for c in rated] == ["unsloth/Qwen3.8-27B-GGUF"]

    # floor 400 -> nothing survives
    none = llama_ai.discover_top_tier(limit=5, total_ram_bytes=48 * 1024 ** 3,
                                      headroom_bytes=3 * 1024 ** 3, min_trending_score=400)
    assert none == []


def test_discover_top_tier_one_per_provider(monkeypatch):
    """discover_top_tier must return at most ONE candidate per provider (owner),
    so a variety of popular providers is offered, not many quants of one."""
    repos = [
        {"repo": "unsloth/Qwen3.8-27B-GGUF", "downloads": 1, "likes": 1, "trendingScore": 300},
        {"repo": "unsloth/Qwen3.8-27B-UD-GGUF", "downloads": 1, "likes": 1, "trendingScore": 280},
        {"repo": "orcarouter/Qwen3.8-27B-Uncensored-GGUF", "downloads": 1, "likes": 1,
         "trendingScore": 120},
    ]

    def fake_trending(limit=25):
        return repos

    def fake_files(repo):
        return [{"path": "model-Q8_0.gguf", "size_bytes": 5 * 1024 ** 3, "size_gb": 5.0}]

    monkeypatch.setattr(llama_ai, "_trending_gguf_repos", fake_trending)
    monkeypatch.setattr(llama_ai, "_repo_gguf_files", fake_files)
    monkeypatch.setattr(llama_ai, "MIN_TOP_TIER_GB", 1.0)

    result = llama_ai.discover_top_tier(limit=5, total_ram_bytes=48 * 1024 ** 3,
                                        headroom_bytes=3 * 1024 ** 3, min_trending_score=0)
    owners = [c["repo"].split("/", 1)[0] for c in result]
    assert owners == ["unsloth", "orcarouter"], "one candidate per provider, best owner first"
    assert len(owners) == len(set(owners)), "no duplicate provider"
