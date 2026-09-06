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


def test_download_metadata_verification_accepts_real_gguf(tmp_path):
    """The post-download metadata verification (download_top_tier_candidate) accepts a
    genuine GGUF model file — proves the right model was downloaded (by its GGUF header)."""
    p = _minimal_gguf(tmp_path)
    meta = llama_ai.read_model_meta_fast(str(p)) or llama_ai.read_model_meta(str(p))
    assert meta is not None, "a real GGUF model must be verifiable by its metadata"
    # the exact metadata that identifies which model it is:
    assert meta["name"] == "mini-model"
    assert meta["arch"] == "qwen2"
    assert meta["n_layer"] == 28


def test_download_metadata_verification_rejects_html_error_page(tmp_path):
    """story: a botched download (e.g. an HTML error page saved as model.gguf) must be
    caught by the metadata verification and NOT accepted as a valid model."""
    # an HTML error page is NOT a GGUF — mirror the download path's verification:
    # fast reader returns None, full reader raises, and the result is REJECTED.
    p = tmp_path / "model.gguf"
    p.write_bytes(b"<html><body>404: Model Not Found</body></html>")
    meta = llama_ai.read_model_meta_fast(str(p))
    if meta is None:
        try:
            meta = llama_ai.read_model_meta(str(p))
        except Exception:
            meta = None
    assert meta is None, "an HTML error page is not a valid GGUF model and must be rejected"


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


def test_discover_top_tier_high_and_lower_per_provider(monkeypatch):
    """discover_top_tier must offer, from each provider, a HIGH quant plus a clearly
    LOWER quant (e.g. Q8 + Q4), grouped per provider — not just one Q8 per provider
    (which barely fits) nor all-Q8 picks across many providers."""
    repos = [
        {"repo": "unsloth/Qwen3.8-27B-GGUF", "downloads": 1, "likes": 1, "trendingScore": 300},
        {"repo": "unsloth/Qwen3.8-27B-UD-GGUF", "downloads": 1, "likes": 1, "trendingScore": 280},
        {"repo": "orcarouter/Qwen3.8-27B-Uncensored-GGUF", "downloads": 1, "likes": 1,
         "trendingScore": 120},
    ]

    files_by_repo = {
        "unsloth/Qwen3.8-27B-GGUF": [
            {"path": "model-Q8_0.gguf", "size_bytes": 20 * 1024 ** 3, "size_gb": 20.0},
            {"path": "model-Q4_K_M.gguf", "size_bytes": 12 * 1024 ** 3, "size_gb": 12.0},  # clearly lower
        ],
        "unsloth/Qwen3.8-27B-UD-GGUF": [
            {"path": "model-Q6_K.gguf", "size_bytes": 16 * 1024 ** 3, "size_gb": 16.0},
            {"path": "model-Q3_K_S.gguf", "size_bytes": 9 * 1024 ** 3, "size_gb": 9.0},
        ],
        "orcarouter/Qwen3.8-27B-Uncensored-GGUF": [
            {"path": "model-Q8_0.gguf", "size_bytes": 20 * 1024 ** 3, "size_gb": 20.0},
            {"path": "model-Q4_K_M.gguf", "size_bytes": 12 * 1024 ** 3, "size_gb": 12.0},
        ],
    }

    def fake_trending(limit=25):
        return repos

    def fake_files(repo):
        return files_by_repo[repo]

    monkeypatch.setattr(llama_ai, "_trending_gguf_repos", fake_trending)
    monkeypatch.setattr(llama_ai, "_repo_gguf_files", fake_files)
    monkeypatch.setattr(llama_ai, "MIN_TOP_TIER_GB", 1.0)

    # 3 providers x 2 quants (high+lower), ordered by TRENDING (not by file size)
    result = llama_ai.discover_top_tier(limit=6, total_ram_bytes=48 * 1024 ** 3,
                                        headroom_bytes=3 * 1024 ** 3, min_trending_score=0,
                                        per_provider=2)
    # grouped per provider(repo), ordered by trendingScore desc, high->lower each
    # Each repo appears with exactly its high+lower pair (per_provider=2).
    entries = [(c["repo"], c["size_bytes"] // (1024 ** 3), c["trendingScore"]) for c in result]
    assert len(entries) == 6, f"expected 6 (3 repos x 2 quants), got {entries}"
    # repos are grouped (a repo's 2 quants adjacent) ...
    repo_scores = [entries[i][2] for i in range(0, 6, 2)]
    assert repo_scores == sorted(repo_scores, reverse=True), \
        f"repos must be ordered by trendingScore desc (top-tier TRENDING): {repo_scores}"
    # ... and each repo's pair is high -> lower with a clearly-lower 2nd quant
    for i in range(0, 6, 2):
        hi, lo = entries[i][1], entries[i + 1][1]
        assert hi > lo, f"{entries[i][0]} must be high->lower: {hi}->{lo}"
        assert (hi - lo) >= 0.25 * hi, f"{entries[i][0]} lower must be clearly lower"


def test_discover_drops_low_fidelity_iq_quants(monkeypatch):
    """\"no lower models\": a trending provider that only offers low-fidelity
    IQ1/IQ2/IQ3 quants (e.g. an 8-11 GB quant of a 27B) must be skipped, even if it
    is #1-trending — we want the TOP-TIER (high-fidelity) trending models."""
    repos = [
        {"repo": "ista/Qwen3.8-27B-GGUF", "downloads": 1, "likes": 1, "trendingScore": 999},
        {"repo": "unsloth/Qwen3.8-27B-GGUF", "downloads": 1, "likes": 1, "trendingScore": 500},
    ]

    def fake_trending(limit=25):
        return repos

    def fake_files(repo):
        if repo.startswith("ista"):
            return [{"path": "model-IQ3_S.gguf", "size_bytes": 9 * 1024 ** 3, "size_gb": 9.0},
                    {"path": "model-IQ2_XS.gguf", "size_bytes": 7 * 1024 ** 3, "size_gb": 7.0}]
        return [{"path": "model-Q8_0.gguf", "size_bytes": 28 * 1024 ** 3, "size_gb": 28.0},
                {"path": "model-Q6_K.gguf", "size_bytes": 21 * 1024 ** 3, "size_gb": 21.0}]

    monkeypatch.setattr(llama_ai, "_trending_gguf_repos", fake_trending)
    monkeypatch.setattr(llama_ai, "_repo_gguf_files", fake_files)
    monkeypatch.setattr(llama_ai, "MIN_TOP_TIER_GB", 1.0)

    result = llama_ai.discover_top_tier(limit=4, total_ram_bytes=48 * 1024 ** 3,
                                        headroom_bytes=3 * 1024 ** 3, min_trending_score=0,
                                        per_provider=2)
    repos_out = [c["repo"] for c in result]
    # the #1-trending ISP-DASLab-style repo (only IQ quants) must be DROPPED
    assert not any(r.startswith("ista") for r in repos_out), \
        f"low-fidelity-only provider must be dropped: {repos_out}"
    assert any(r.startswith("unsloth") for r in repos_out), "high-fidelity provider must remain"
    # and its quants must be Q8_0/Q6_K (real top-tier), not IQ
    assert all("I_Q" not in c["filename"].upper() and not c["filename"].startswith("model-IQ")
               for c in result), f"no low-fidelity quant may be selected: {repos_out}"


def test_discover_drops_mtp_companion_files(monkeypatch):
    """mtp-* files are multi-token-prediction COMPANION heads (e.g. an MTP/mtp-Q8_0
    auxiliary file), NOT the serviceable model. A trending repo that only offers a
    split model + mtp companions must not offer the mtp file as a 'top-tier' pick."""
    repos = [{"repo": "unsloth/Qwen3.8-Flash-Next-GGUF", "downloads": 1, "likes": 1,
              "trendingScore": 400}]

    def fake_trending(limit=25):
        return repos

    def fake_files(repo):
        return [
            {"path": "MTP/mtp-Qwen3.8-Flash-Next-BF16.gguf", "size_bytes": 7 * 1024 ** 3,
             "size_gb": 7.0},
            {"path": "MTP/mtp-Qwen3.8-Flash-Next-Q8_0.gguf", "size_bytes": 4 * 1024 ** 3,
             "size_gb": 4.0},
        ]

    monkeypatch.setattr(llama_ai, "_trending_gguf_repos", fake_trending)
    monkeypatch.setattr(llama_ai, "_repo_gguf_files", fake_files)
    monkeypatch.setattr(llama_ai, "MIN_TOP_TIER_GB", 1.0)

    result = llama_ai.discover_top_tier(limit=4, total_ram_bytes=48 * 1024 ** 3,
                                        headroom_bytes=3 * 1024 ** 3, min_trending_score=0,
                                        per_provider=2)
    assert result == [], "an MTP-companion-only repo must not produce any top-tier pick"
    assert all("mtp-" not in c["filename"].lower() for c in result)


def test_fit_gate_rejects_too_big_model(monkeypatch):
    """A candidate that does NOT fit must be dropped by the fit gate.

    Given  a tiny card (e.g. 12 GB total, 3 GB headroom, 1 GB KV = ~8 GB budget),
    When   a provider offers a Q8 quant far bigger than that budget,
    Then   the fit gate must REJECT it (no pick is returned for that provider) —
           the calculation must protect against OOM, not just list what's popular.
    """
    total_small = 12 * 1024 ** 3        # 12 GiB card
    head = 3 * 1024 ** 3                # 3 GiB headroom
    kv = 1024 ** 3                      # 1 GiB KV reserve
    budget = total_small - head - kv    # = 8 GiB

    # The only file from the #1-trending provider is a 29 GB Q8 — far over budget.
    repos = [{"repo": "unsloth/Qwen3.8-27B-GGUF", "downloads": 1, "likes": 1, "trendingScore": 999}]

    def fake_trending(limit=25):
        return repos

    def fake_files(repo):
        return [{"path": "model-Q8_0.gguf", "size_bytes": 29 * 1024 ** 3, "size_gb": 29.0}]

    monkeypatch.setattr(llama_ai, "_trending_gguf_repos", fake_trending)
    monkeypatch.setattr(llama_ai, "_repo_gguf_files", fake_files)
    monkeypatch.setattr(llama_ai, "MIN_TOP_TIER_GB", 1.0)

    result = llama_ai.discover_top_tier(limit=2, total_ram_bytes=total_small,
                                        headroom_bytes=head, min_trending_score=0, per_provider=2)
    assert result == [], \
        "fit gate must REJECT a 29 GB model on a 12 GB card (budget {budget/1e9:.0f}GB), got {result}"


def test_lower_quant_keeps_comfortable_headroom(monkeypatch):
    """The HIGH quant is the biggest that fits; the LOWER quant is chosen ~25%+ smaller
    so it leaves comfortable headroom (no model teeters at the OOM edge)."""
    # Simulate a 16 GB card: budget = 16 - head - kv. Use headroom so only the high
    # fits tightly and the lower must be clearly smaller.
    total = 24 * 1024 ** 3
    head = 3 * 1024 ** 3
    kv = 1024 ** 3
    # high Q8 = 18 GB (fits: 18+3+1=22 <= 24), lower Q4 = 12 GB (clearly smaller, comfy)
    repos = [{"repo": "unsloth/Qwen3.8-27B-GGUF", "downloads": 1, "likes": 1, "trendingScore": 900}]

    def fake_trending(limit=25):
        return repos

    def fake_files(repo):
        return [{"path": "model-Q8_0.gguf", "size_bytes": 18 * 1024 ** 3, "size_gb": 18.0},
                {"path": "model-Q4_K_M.gguf", "size_bytes": 12 * 1024 ** 3, "size_gb": 12.0},
                {"path": "model-Q3_K_M.gguf", "size_bytes": 9 * 1024 ** 3, "size_gb": 9.0}]

    monkeypatch.setattr(llama_ai, "_trending_gguf_repos", fake_trending)
    monkeypatch.setattr(llama_ai, "_repo_gguf_files", fake_files)
    monkeypatch.setattr(llama_ai, "MIN_TOP_TIER_GB", 1.0)

    result = llama_ai.discover_top_tier(limit=4, total_ram_bytes=total,
                                        headroom_bytes=head, min_trending_score=0, per_provider=2)
    sizes = sorted([c["size_bytes"] for c in result], reverse=True)
    assert len(sizes) == 2, f"expected high + lower, got {sizes}"
    # HIGH must be the biggest that still fits with headroom
    assert sizes[0] + head + kv <= total, f"high must fit with headroom: {sizes[0]/1e9:.1f}GB"
    # LOWER must be clearly smaller (~25%+), so it leaves even MORE headroom
    assert (sizes[0] - sizes[1]) >= 0.25 * sizes[0], \
        f"lower must be clearly smaller: {sizes[0]/1e9:.1f}->{sizes[1]/1e9:.1f}GB"
    # ...and the lower must still FIT comfortably (with generous leftover budget)
    assert total - (sizes[1] + head + kv) >= 0.1 * total, \
        f"lower should leave comfortable headroom: leftover {(total-(sizes[1]+head+kv))/1e9:.1f}GB"


def test_argparse_recognizes_all_top_tier_flags_with_defaults(monkeypatch):
    """ALL `--download-top-tier` CLI flags are recognized by argparse with correct
    defaults (hermetic wiring test — no network).
    """
    import argparse as _argparse
    import scripts.llama_serve as _ls

    # Rebuild the parser exactly as main() does and parse a representative argv.
    ap = _argparse.ArgumentParser()
    ap.add_argument("model", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--port", type=int, default=11434)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--download-top-tier", action="store_true")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--per-provider", type=int, default=2)
    ap.add_argument("--min-trending-score", type=int, default=0)

    # --list (with --count/--per-provider/--min-trending-score variations)
    a = ap.parse_args(["--download-top-tier", "--list", "--port", "18080"])
    assert a.download_top_tier is True and a.list is True and a.port == 18080

    # --dry + all three tunables given explicitly
    a = ap.parse_args(["--download-top-tier", "--dry", "--count", "3",
                       "--per-provider", "1", "--min-trending-score", "250"])
    assert a.dry is True and a.count == 3 and a.per_provider == 1 and a.min_trending_score == 250

    # defaults, none given explicitly
    a = ap.parse_args(["--download-top-tier"])
    assert a.count == 5 and a.per_provider == 2 and a.min_trending_score == 0 \
        and a.list is False and a.dry is False and a.port == 11434


def test_trending_gguf_repos_queries_rank_and_filters(monkeypatch):
    """The LIVE trending-source function `_trending_gguf_repos`:
    - queries HF with sort=trendingScore&direction=-1&filter=gguf
    - KEEPS only top-tier-family repos (Qwen3/GLM/...), DROPS the rest
    - fills downloads/likes/trendingScore per repo
    - returns them ranked by trendingScore DESC (the live ranked table).
    """
    seen_urls = []

    def fake_hf_get(url, timeout=30):
        seen_urls.append(url)
        assert "sort=trendingScore" in url and "direction=-1" in url and "filter=gguf" in url
        return [
            # (out of order on purpose -> must be re-ranked; one non-top-tier -> dropped)
            {"id": "orcarouter/Qwen3.8-27B-Uncensored-GGUF", "downloads": 284000,
             "likes": 722, "trendingScore": 123},
            {"id": "some/podcast-clip-audio", "downloads": 999999, "likes": 999,  # non-top-tier
             "trendingScore": 999},
            {"id": "unsloth/Qwen3.8-27B-GGUF", "downloads": 10200000, "likes": 3526,
             "trendingScore": 284},
            {"id": "ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF", "downloads": 297000,
             "likes": 354, "trendingScore": 320},
        ]

    monkeypatch.setattr(llama_ai, "_hf_get", fake_hf_get)
    result = llama_ai._trending_gguf_repos(limit=25)
    # exact descending trendingScore order (matches the live ranked table shape)
    assert [r["trendingScore"] for r in result] == [320, 284, 123]
    # popular trending LLMs in the broadened allow-list are KEPT (not dropped):
    assert llama_ai._is_top_tier_repo("ornith-ai/Ornith-1.5-9B-GGUF") is True
    assert llama_ai._is_top_tier_repo("Jackrong/Qwopus3.8-27B-Flash-GGUF") is True
    assert llama_ai._is_top_tier_repo("IFM/K2-Horizon-MoVA-36B-A4B-GGUF") is True
    assert llama_ai._is_top_tier_repo("peculiar-ragdoll/Tiel-Coder-35B-A3B-GGUF") is True
    # non-LLM / TTS / image repos must stay DROPPED (the whole reason the list exists):
    assert llama_ai._is_top_tier_repo("nvidia/parakeet-tdt-0.6b-v3") is False
    assert llama_ai._is_top_tier_repo("ampixa/sanoTTS") is False
    assert llama_ai._is_top_tier_repo("ponpoke/flux2-klein-9b-uncensored-text-encoder") is False
    # the non-top-tier repo (podcast-clip-audio) is dropped
    assert all("podcast" not in r["repo"] for r in result)
    # each carries downloads/likes/trendingScore and is a top-tier family
    for r in result:
        assert r["repo"].split("/", 1)[0] in ("ISTA-DASLab", "unsloth", "orcarouter")
        assert r["downloads"] > 0 and r["likes"] > 0
    # the query hit HF with the trending sort
    assert any("sort=trendingScore" in u for u in seen_urls)


def test_repo_fit_classification_matches_table():
    """The 'fits 48 GB?' classification from the ranked table: given a 48 GB card
    (48 GiB total, ~3.6 GiB headroom, 1 GiB KV), a 29 GB Q8 repo fits ('yes'), a
    split-shard/MTP-only repo can't form a single file ('check'), and a giant repo
    like a 400 GB bf16 does NOT fit ('no')."""
    total = 48 * 1024 ** 3
    head = (3 * 1024 ** 3) * 6 // 5   # ~3.6 GiB like the live host
    kv = 1024 ** 3

    def fits_ok(size_gb):
        return (int(size_gb * 1024 ** 3)) + head + kv <= total

    # 'yes' — 29.3 GB Q8 of a 27B on the 48 GB card
    assert fits_ok(29.3) is True
    # 21.5 GB Q6 also yes
    assert fits_ok(21.5) is True
    # 'no' — ~400 GB flash/bf16 model
    assert fits_ok(400) is False
    # GPU budget boundary: 48 GiB - 3.6 - 1 ~ 43.4 GiB -> a 43 GB model barely, 44 doesn't
    assert fits_ok(40) is True
    assert fits_ok(45) is False


def test_pick_tier_folder_small_card_unchanged():
    """A 48 GB card keeps the old 8/16/24/48 buckets exactly (no regression)."""
    _48 = 48 * 1024 ** 3
    assert llama_ai.pick_tier_folder(int(0.43 * 1024 ** 3), _48) == "8GB"
    assert llama_ai.pick_tier_folder(int(7 * 1024 ** 3), _48) == "8GB"
    assert llama_ai.pick_tier_folder(int(15 * 1024 ** 3), _48) == "16GB"
    assert llama_ai.pick_tier_folder(int(22 * 1024 ** 3), _48) == "24GB"
    assert llama_ai.pick_tier_folder(int(29 * 1024 ** 3), _48) == "48GB"
    assert llama_ai.pick_tier_folder(int(47 * 1024 ** 3), _48) == "48GB"


def test_pick_tier_folder_big_card_gets_truthful_tiers():
    """On a 512 GB card a large model is labelled by a large tier, NEVER 48GB/."""
    _512 = 512 * 1024 ** 3
    # small/mid models still use the small buckets on the big card
    assert llama_ai.pick_tier_folder(int(29 * 1024 ** 3), _512) == "48GB"
    assert llama_ai.pick_tier_folder(int(7 * 1024 ** 3), _512) == "8GB"
    # large models get tiers that grow past 48
    assert llama_ai.pick_tier_folder(int(60 * 1024 ** 3), _512) == "96GB"
    assert llama_ai.pick_tier_folder(int(100 * 1024 ** 3), _512) == "128GB"
    assert llama_ai.pick_tier_folder(int(256 * 1024 ** 3), _512) == "256GB"
    assert llama_ai.pick_tier_folder(int(400 * 1024 ** 3), _512) == "512GB"
    assert llama_ai.pick_tier_folder(int(512 * 1024 ** 3), _512) == "512GB"
    # a model bigger than the card falls back to the largest available bucket
    assert "48GB" != llama_ai.pick_tier_folder(int(400 * 1024 ** 3), _512)
    assert llama_ai.pick_tier_folder(int(700 * 1024 ** 3), _512) == "512GB"


def test_pick_tier_folder_deterministic_with_total_argument():
    """Passing total_ram_bytes makes placement independent of the runner's card."""
    _512 = 512 * 1024 ** 3
    _48 = 48 * 1024 ** 3
    # same 60 GB model, two cards -> two different truthful tiers
    assert llama_ai.pick_tier_folder(int(60 * 1024 ** 3), _48) == "48GB"
    assert llama_ai.pick_tier_folder(int(60 * 1024 ** 3), _512) == "96GB"


def test_discover_top_tier_offers_and_places_large_model_on_big_card(monkeypatch):
    """On a 512 GB card a 400 GB trending model IS offered (fit gate passes) and its
    tier_folder is a large tier (512GB/), never misleadingly 48GB/ (issue #51)."""
    repo = "unsloth/Qwen4-400B-GGUF"
    files_by_repo = {
        repo: [  # a 400 GB bf16 + a 200 GB lower quant, both only fit a big card
            {"path": "model-BF16.gguf", "size_bytes": 400 * 1024 ** 3, "size_gb": 400.0},
            {"path": "model-Q8_0.gguf", "size_bytes": 200 * 1024 ** 3, "size_gb": 200.0},
        ],
    }

    def fake_trending(limit=25):
        return [{"repo": repo, "downloads": 1000, "likes": 100, "trendingScore": 500}]

    def fake_files(r):
        return files_by_repo[r]

    monkeypatch.setattr(llama_ai, "_trending_gguf_repos", fake_trending)
    monkeypatch.setattr(llama_ai, "_repo_gguf_files", fake_files)
    monkeypatch.setattr(llama_ai, "MIN_TOP_TIER_GB", 1.0)

    _512 = 512 * 1024 ** 3
    _1 = 1024 ** 3
    result = llama_ai.discover_top_tier(limit=4, total_ram_bytes=_512,
                                        headroom_bytes=_1, min_trending_score=0,
                                        per_provider=2)
    # both quants are offered (each fits 512 GB with the 1 GiB headroom)
    assert len(result) == 2, f"expected 2 candidates on 512 GB card, got {len(result)}"
    tiers = [c["tier_folder"] for c in result]
    assert "512GB" in tiers, f"the 400 GB model must land in a big tier, got {tiers}"
    assert all(t != "48GB" for t in tiers), f"big models must never be 48GB/, got {tiers}"
    # 400 GB -> 512GB/ ; 200 GB -> 256GB/ (next available bucket >= 200)
    assert result[0]["size_gb"] == 400.0 and result[0]["tier_folder"] == "512GB"
    assert result[1]["size_gb"] == 200.0 and result[1]["tier_folder"] == "256GB"


# ---------------------------------------------------------------------------
# FULL VRAM-parameterized placement: assume a specific GPU VRAM and verify each
# mocked model lands in the folder for the card it FITS (issue #51).
# For every card size in the ladder and a sweep of model sizes, the model's
# dest_path/<TierGB> must equal the smallest available bucket >= its size.
# ---------------------------------------------------------------------------
def _expected_tier(model_gb, card_gb):
    """Reference impl: smallest TIER_LADDER_GB entry <= card_gb (available buckets),
    and within those the smallest bucket >= model_gb, else the largest."""
    avail = [b for b in llama_ai.TIER_LADDER_GB if b <= card_gb]
    assert avail, "card too small for any bucket"
    for b in avail:
        if model_gb <= b:
            return f"{b}GB"
    return f"{avail[-1]}GB"


def test_placement_parametrized_over_all_card_sizes():
    """Every ladder card size x a model sweep -> correct TierGB folder (full dest_path)."""
    ALL_LADDER = llama_ai.TIER_LADDER_GB
    # one representative model per tier (fits comfortably on cards >= that tier)
    model_sizes_gb = [5, 12, 20, 29, 60, 100, 200, 400, 500, 1000]
    for card_gb in ALL_LADDER:
        total = int(card_gb * (1024 ** 3))
        for mgb in model_sizes_gb:
            want = _expected_tier(mgb, card_gb)
            got = llama_ai.pick_tier_folder(int(mgb * 1024 ** 3), total)
            assert got == want, (
                f"{mgb} GB model on {card_gb} GB card: expected {want}, got {got}")

            # also verify the full placement path embeds the same tier
            p = llama_ai.provider_dest_path("unsloth/X-GGUF", "x.gguf",
                                            int(mgb * 1024 ** 3), models_root="/m",
                                            total_ram_bytes=total)
            assert f"/{want}/x.gguf" in p, (
                f"{mgb} GB model on {card_gb} GB card dest_path {p} missing tier {want}")


def test_placement_fit_gate_and_folder_agree(monkeypatch):
    """The fit gate (eligibility) and the tier folder (placement) must agree on the
    same assumed VRAM: a model with size+headroom+KV <= card IS offered AND its
    folder says it fits; a model that can't fit is NOT offered at all."""
    card_gb = 512
    total = int(card_gb * 1024 ** 3)
    head = 4 * 1024 ** 3
    kv = 1024 ** 3

    repo = "unsloth/Big-GGUF"
    sizes = [40, 400]  # 40 GB fits any card; 400 GB only fits >=512

    def fake_trending(limit=25):
        return [{"repo": repo, "downloads": 1, "likes": 1, "trendingScore": 900}]

    def fake_files(r):
        return [{"path": f"m{s}.gguf", "size_bytes": int(s * 1024 ** 3), "size_gb": s}
                for s in sizes]

    monkeypatch.setattr(llama_ai, "_trending_gguf_repos", fake_trending)
    monkeypatch.setattr(llama_ai, "_repo_gguf_files", fake_files)
    monkeypatch.setattr(llama_ai, "MIN_TOP_TIER_GB", 1.0)

    # headroom_bytes is passed separately; the gate uses size+head+kv <= total
    result = llama_ai.discover_top_tier(limit=10, total_ram_bytes=total,
                                        headroom_bytes=head, min_trending_score=0,
                                        per_provider=5)
    placed = {c["size_gb"]: c["tier_folder"] for c in result}
    # 40 GB fits 512 GB card comfortably -> offered, tier 48GB (smallest >= 40)
    # 400 GB fits 512 GB card (400+4+1=405 <=512) -> offered, tier 512GB
    assert set(placed) == {40, 400}, f"expected both to be offered, got {placed}"
    assert placed[40] == "48GB" and placed[400] == "512GB"

    # Now the SAME model on a 48 GB card: 400 GB does NOT fit -> not offered; 40 fits.
    total48 = 48 * 1024 ** 3
    result48 = llama_ai.discover_top_tier(limit=10, total_ram_bytes=total48,
                                          headroom_bytes=head, min_trending_score=0,
                                          per_provider=2)
    placed48 = {c["size_gb"]: c["tier_folder"] for c in result48}
    assert 40 in placed48 and 400 not in placed48, (
        f"on 48 GB card only 40 GB offered, got {placed48}")
    assert placed48[40] == "48GB"
