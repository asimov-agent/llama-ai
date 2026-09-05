"""Acceptance tests for the top-tier trending download feature (issue #49).

REAL end-to-end tests — NO mocks, NO skips. They hit the live Hugging Face API,
the real `hf` downloader, and the real GPU/CPU card memory read. No test here may
be skipped; if `hf` is genuinely absent we hard-fail (it is installed by default
on the host and in the CI image). The dynamic memory read works on both macOS
(Metal) and Linux/CI (CPU), so the fit gate picks the top-tier quant that fits
whichever card the test runs on.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import scripts.llama_serve as llama_ai  # noqa: E402

pytestmark = pytest.mark.acceptance


def _real_hf() -> str:
    """Return the real hf binary; FAIL (not skip) if it is genuinely absent."""
    hf = os.environ.get("HF_BIN") or shutil.which("hf")
    assert hf and Path(hf).is_file(), (
        "hf CLI not installed — cannot run real top-tier acceptance tests. "
        "pip install huggingface_hub (or set HF_BIN).")
    return hf


def test_real_trending_query_and_dynamic_ram():
    """Live HF trending + dynamic card read return sane results on host OR CPU."""
    total = llama_ai.read_total_ram_bytes()
    assert total > 1024 ** 3, "total RAM must be > 1 GB"
    headroom = llama_ai.read_current_headroom_bytes(total)
    assert headroom > 0, "headroom must be positive"
    repos = llama_ai._trending_gguf_repos(limit=25)
    assert isinstance(repos, list)
    assert len(repos) > 0, "expected top-tier trending GGUF repos from the live HF API"
    for r in repos:
        assert "repo" in r, "each trending entry has a repo id"
        assert r["repo"].count("/") == 1, "repo id must be owner/name"


def test_discover_top_tier_fit_gate():
    """discover_top_tier must ONLY return candidates that FIT the actual card."""
    total = llama_ai.read_total_ram_bytes()
    head = llama_ai.read_current_headroom_bytes(total)
    cands = llama_ai.discover_top_tier(limit=4, total_ram_bytes=total, headroom_bytes=head)
    assert cands, "expected at least one top-tier candidate to fit the actual card"
    for c in cands:
        # fit gate: size + headroom + KV reserve must be <= total
        assert c["size_bytes"] + head + (1024 ** 3) <= total, \
            f"candidate {c['repo']}::{c['filename']} does NOT fit the card"
        # provider-aware path: <root>/<owner>/<family>/<TierGB>/<file>
        owner, family = c["repo"].split("/", 1)
        assert c["dest_path"].startswith(str(Path(llama_ai.MODELS_ROOT) / owner / family))
        assert c["filename"] == Path(c["dest_path"]).name
        assert c["size_gb"] >= llama_ai.MIN_TOP_TIER_GB, "top-tier must not be a toy"


def test_provider_placement_specific():
    """provider_dest_path must produce <root>/<owner>/<family>/<TierGB>/<file>."""
    repo = "unsloth/Qwen3.8-27B-GGUF"
    fn = "Qwen3.8-27B-Q8_0.gguf"
    root = "/tmp/llama-models-test"
    p = llama_ai.provider_dest_path(repo, fn, 29 * 1024 ** 3, models_root=root)
    assert p == "/tmp/llama-models-test/unsloth/Qwen3.8-27B-GGUF/48GB/Qwen3.8-27B-Q8_0.gguf"
    p2 = llama_ai.provider_dest_path(repo, fn, 15 * 1024 ** 3, models_root=root)
    assert p2.endswith("/16GB/Qwen3.8-27B-Q8_0.gguf")
    p3 = llama_ai.provider_dest_path(repo, fn, 22.5 * 1024 ** 3, models_root=root)
    assert p3.endswith("/24GB/Qwen3.8-27B-Q8_0.gguf")


def test_real_download_idempotent():
    """Actually download the #1 top-tier pick (or resign/stay if already complete)
    via the real hf CLI, then verify completeness + provider placement + idempotency.

    This performs a REAL download into the card-aware tier folder. It is NOT a skip:
    if the matching quant is already fully present (same expected size), the resume/
    idempotency path is exercised and asserted; otherwise a genuine download runs.
    """
    _real_hf()
    total = llama_ai.read_total_ram_bytes()
    head = llama_ai.read_current_headroom_bytes(total)
    cands = llama_ai.discover_top_tier(limit=1, total_ram_bytes=total, headroom_bytes=head)
    assert cands, "expected a top-tier candidate to fit the actual card"
    cand = cands[0]
    final = llama_ai.download_top_tier_candidate(cand, models_root=None)
    # real complete file at the provider-aware path (size == expected)
    assert Path(final).is_file(), f"downloaded file missing: {final}"
    size = Path(final).stat().st_size
    assert size >= cand["size_bytes"] - (64 * 1024 * 1024), \
        f"file incomplete: {size/1e9:.2f} GB vs expected {cand['size_bytes']/1e9:.2f} GB"
    assert str(Path(final)) == cand["dest_path"], "file must land at provider-aware dest_path"
    # idempotent (already complete -> no re-download error, same path)
    final2 = llama_ai.download_top_tier_candidate(cand, models_root=None)
    assert final2 == final, "second download must be idempotent (same path)"


def test_tiny_model_download_retest_and_update_recovery():
    """Download a TINY real model, re-run idempotently, then simulate a same-name
    content update and verify REFRESH mode re-fetches the CORRECT bytes.

    Models the exact upstream scenario: same filename, same size, new content.
    A size-only guard would silently keep the stale copy; this proves the
    etag/content-hash path re-downloads the changed file. No mocks — real `hf`.
    """
    _real_hf()
    TF = "2026-09-05-qwen05b-tinytest"
    repo = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
    fn = "qwen2.5-0.5b-instruct-q4_0.gguf"
    # real size from the HF tree API
    tree = llama_ai._repo_gguf_files(repo)
    real = next(f for f in tree if f["path"] == fn)
    cand = {
        "repo": repo,
        "filename": fn,
        "size_bytes": real["size_bytes"],
        "size_gb": real["size_gb"],
        "tier_folder": "8GB",
        "dest_path": f"/tmp/{TF}/Qwen/Qwen2.5-0.5B-Instruct-GGUF/8GB/{fn}",
    }
    Path(f"/tmp/{TF}").mkdir(parents=True, exist_ok=True)
    try:
        # 1. first real download
        final = llama_ai.download_top_tier_candidate(cand, models_root=f"/tmp/{TF}")
        assert os.path.isfile(final)
        assert os.path.getsize(final) >= cand["size_bytes"] - (64 * 1024 * 1024)
        good_bytes = open(final, "rb").read()
        # 2. idempotent re-run -> same path, no error
        final2 = llama_ai.download_top_tier_candidate(cand, models_root=f"/tmp/{TF}")
        assert final2 == final
        # 3. simulate SAME-NAME SAME-SIZE content update: overwrite with same-length rot13 garbage
        corrupt = bytes((b ^ 0x5A) & 0xFF for b in good_bytes)
        with open(final, "wb") as f:
            f.write(corrupt)
        assert os.path.getsize(final) == cand["size_bytes"]  # size unchanged
        assert open(final, "rb").read() != good_bytes        # content IS different now
        # 4. REFRESH mode must re-fetch the CORRECT bytes (etag differs, size same)
        recovered = llama_ai.download_top_tier_candidate(cand, models_root=f"/tmp/{TF}")
        assert recovered == final
        assert open(final, "rb").read() == good_bytes, \
            "refresh mode must re-download the correct bytes after a same-size content update"
    finally:
        shutil.rmtree(f"/tmp/{TF}", ignore_errors=True)
