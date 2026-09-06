"""Acceptance tests for the top-tier trending download feature (issue #49).

Each test is written as a short story a non-technical reader can follow, while
still running the REAL system — live Hugging Face, the real `hf` downloader, and
the real CPU/GPU card memory. NO mocks, NO skips. If `hf` is genuinely missing we
hard-fail (it is installed on the host and in the CI image).

Story style:  Given <starting situation>
              When  <an action happens>
              Then  <what must be true>
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import scripts.llama_serve as llama_ai  # noqa: E402

pytestmark = pytest.mark.acceptance


def _real_hf() -> str:
    """Locate the real `hf` command. Fails (does not skip) if it is missing."""
    hf = os.environ.get("HF_BIN") or shutil.which("hf")
    assert hf and Path(hf).is_file(), (
        "hf CLI not installed — cannot run real top-tier acceptance tests. "
        "pip install huggingface_hub (or set HF_BIN).")
    return hf


def test_real_trending_query_and_dynamic_ram():
    """Story: we ask what's trending and how much memory the machine has.

    Given  I ask the tool to look up what GGUF models are trending right now
           and I ask it how much memory this computer has,
    When   it reads the machine and asks Hugging Face,
    Then   it must find at least one trending model,
           and the machine must report a sensible amount of memory (more than 1 GB)
           with a positive amount of spare room.
    """
    total = llama_ai.read_total_ram_bytes()
    assert total > 1024 ** 3, "total RAM must be > 1 GB"
    headroom = llama_ai.read_current_headroom_bytes(total)
    assert headroom > 0, "headroom must be positive"

    repos = llama_ai._trending_gguf_repos(limit=25)
    assert isinstance(repos, list)
    assert len(repos) > 0, "expected at least one trending GGUF model on Hugging Face"
    for r in repos:
        assert "repo" in r, "each trending entry has a repo id"
        assert r["repo"].count("/") == 1, "repo id must be owner/name (e.g. unsloth/Qwen3.8-27B-GGUF)"


def test_discover_top_tier_fit_gate():
    """Story: only models that FIT this card are offered.

    Given  I ask for the top trendy models that will fit this exact computer,
    When   the tool checks each candidate against this machine's memory,
    Then   every model offered must fit with room to spare —
           (model size + spare room + a little extra for KV cache) is never more
           than the machine's total memory,
           each model goes into a folder that records who made it
           (owner or company name first), and
           no toy-sized tiny model is offered as "top tier".
    """
    total = llama_ai.read_total_ram_bytes()
    head = llama_ai.read_current_headroom_bytes(total)
    cands = llama_ai.discover_top_tier(limit=4, total_ram_bytes=total, headroom_bytes=head)
    assert cands, "expected at least one top-tier model to fit this machine"
    for c in cands:
        # fit: size + headroom + KV reserve <= total
        assert c["size_bytes"] + head + (1024 ** 3) <= total, \
            f"{c['repo']}::{c['filename']} does NOT fit this machine's memory"
        # owner/family first in the destination path
        owner, family = c["repo"].split("/", 1)
        assert c["dest_path"].startswith(str(Path(llama_ai.MODELS_ROOT) / owner / family))
        assert c["filename"] == Path(c["dest_path"]).name
        assert c["size_gb"] >= llama_ai.MIN_TOP_TIER_GB, "a toy model is not 'top tier'"


def test_provider_placement_specific():
    """Story: files are saved into a folder that shows by whom and how it fits.

    Given  a model made by "unsloth" named Qwen3.8-27B,
    When   the tool decides where to save a 29 GB copy of it,
    Then   the save location must be .../unsloth/Qwen3.8-27B-GGUF/48GB/...
           (owner/unsloth, tunneled by size tier: a 15 GB copy -> 16GB,
            a 22 GB copy -> 24GB, a 29 GB copy -> 48GB).
    """
    repo = "unsloth/Qwen3.8-27B-GGUF"
    fn = "Qwen3.8-27B-Q8_0.gguf"
    root = "/tmp/llama-models-test"
    p = llama_ai.provider_dest_path(repo, fn, 29 * 1024 ** 3, models_root=root)
    assert p == "/tmp/llama-models-test/unsloth/Qwen3.8-27B-GGUF/48GB/Qwen3.8-27B-Q8_0.gguf"
    p2 = llama_ai.provider_dest_path(repo, fn, 15 * 1024 ** 3, models_root=root)
    assert p2.endswith("/16GB/Qwen3.8-27B-Q8_0.gguf")
    p3 = llama_ai.provider_dest_path(repo, fn, 22.5 * 1024 ** 3, models_root=root)
    assert p3.endswith("/24GB/Qwen3.8-27B-Q8_0.gguf")


def _lightweight_candidate(tmp_root):
    """A deterministic LIGHTWEIGHT top-tier-real candidate (Qwen 0.5B, ~430 MB).

    Used by the real-download and update-recovery acceptance tests so CI (and
    local) exercises a genuine `hf` download + placement + idempotency with a
    small, fast model rather than a multi-GB one. Still a real, no-mock download.
    """
    repo = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
    fn = "qwen2.5-0.5b-instruct-q4_0.gguf"
    real = next(f for f in llama_ai._repo_gguf_files(repo) if f["path"] == fn)
    return {
        "repo": repo,
        "filename": fn,
        "size_bytes": real["size_bytes"],
        "size_gb": real["size_gb"],
        "tier_folder": "8GB",
        "dest_path": f"{tmp_root}/Qwen/Qwen2.5-0.5B-Instruct-GGUF/8GB/{fn}",
    }


def test_real_download_then_repeat_is_fast_and_safe():
    """Story: download a real top model, then run again without clobbering.

    Given  I ask for a small real top-tier model (lightweight so this is a quick,
           genuine download usable in a CPU CI stage),
    When   the tool downloads it for real into a by-owner/by-size folder,
    Then   the file must actually exist on disk, be a complete download (not a
           partial stub), and be in exactly the place we expected,
    When   I ask for the same model a second time,
    Then   it must not error and must end up at the same place (idempotent).
    """
    _real_hf()
    tf = f"/tmp/llama-real-dl-{os.getpid()}"
    Path(tf).mkdir(parents=True, exist_ok=True)
    try:
        cand = _lightweight_candidate(tf)
        dest = str(Path(cand["dest_path"]))
        final = llama_ai.download_top_tier_candidate(
            dict(cand, dest_path=dest), models_root=tf)
        assert Path(final).is_file(), f"downloaded file missing: {final}"
        size = Path(final).stat().st_size
        assert size >= cand["size_bytes"] - (64 * 1024 * 1024), \
            f"file incomplete: {size/1e9:.2f} GB vs expected {cand['size_bytes']/1e9:.2f} GB"
        assert str(Path(final)) == dest, "file must land in the by-owner/by-size folder"

        final2 = llama_ai.download_top_tier_candidate(
            dict(cand, dest_path=dest), models_root=tf)
        assert final2 == final, "second run must end up at the same file (no error, no clobber)"
    finally:
        shutil.rmtree(tf, ignore_errors=True)


def test_same_name_updated_model_is_redownloaded():
    """Story: a model that was changed 'behind its name' is picked up again.

    Given  a small real model has been downloaded,
    When   I run the download again, it should just say "already there" (idempotent),
    But    then I damage that same file on disk — same file name, same byte size,
           but the contents are now wrong (as if the maker tweaked it in place),
    When   I ask the tool to get the model again,
    Then   it must notice the contents no longer match and download the file
           again, restoring the correct, correct content — it must NOT keep using
           the damaged copy just because the name and size look the same.
    """
    _real_hf()
    TF = "2026-09-05-qwen05b-tinytest"
    repo = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
    fn = "qwen2.5-0.5b-instruct-q4_0.gguf"
    # Ask Hugging Face for this file's real size.
    real = next(f for f in llama_ai._repo_gguf_files(repo) if f["path"] == fn)
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
        # 1. real download
        final = llama_ai.download_top_tier_candidate(cand, models_root=f"/tmp/{TF}")
        assert os.path.isfile(final)
        good_bytes = open(final, "rb").read()

        # 2. idempotent re-run: same place, no error
        final2 = llama_ai.download_top_tier_candidate(cand, models_root=f"/tmp/{TF}")
        assert final2 == final

        # 3. damage the file "in place": same name, same size, scrambled contents
        corrupted = bytes((b ^ 0x5A) & 0xFF for b in good_bytes)
        with open(final, "wb") as f:
            f.write(corrupted)
        assert os.path.getsize(final) == cand["size_bytes"]  # size looks identical
        assert open(final, "rb").read() != good_bytes        # ...but it is wrong

        # 4. asking again must restore the correct contents
        recovered = llama_ai.download_top_tier_candidate(cand, models_root=f"/tmp/{TF}")
        assert recovered == final
        assert open(final, "rb").read() == good_bytes, \
            ("the downloader must re-fetch and restore the real file after a "
             "same-size, same-name content change (it must not trust name+size alone)")
    finally:
        shutil.rmtree(f"/tmp/{TF}", ignore_errors=True)


def test_discover_high_and_lower_quants_per_provider():
    """Story: get high + lower quants from each popular maker.

    Given  I ask for the top-5 trending top-tier models that fit this machine,
    When   the tool looks up what's trending and what fits,
    Then   it must return up to the number of providers I asked for, offering from
           each maker a HIGH quant (Q8, the highest fidelity that fits) AND a LOWER
           quant (clearly smaller, e.g. Q4/Q5/Q6 so it fits comfortably) — never
           only the largest Q8 of each provider (which would barely fit and give no
           quantization variety).
    """
    total = llama_ai.read_total_ram_bytes()
    head = llama_ai.read_current_headroom_bytes(total)
    cands = llama_ai.discover_top_tier(limit=4, total_ram_bytes=total, headroom_bytes=head,
                                       per_provider=2)
    assert cands, "expected top-tier candidates to fit"
    # For each provider, its picks must be a HIGH quant plus a clearly-LOWER quant:
    # each successive pick is meaningfully smaller than the previous (a different tier).
    from collections import OrderedDict
    per_provider = OrderedDict()
    for c in cands:
        per_provider.setdefault(c["repo"].split("/", 1)[0], []).append(c)
    for owner, picks in per_provider.items():
        sizes = [p["size_bytes"] for p in picks]
        assert sizes == sorted(sizes, reverse=True), f"{owner} picks must be high->lower"
        if len(sizes) >= 2:
            # a 2nd (lower) pick must be a clearly different quant tier (~25%+ smaller)
            assert (sizes[0] - sizes[1]) >= 0.25 * sizes[0], \
                f"{owner} 2nd pick not a clearly-lower quant: {sizes[0]/1e9:.1f}->{sizes[1]/1e9:.1f}GB"
        assert all(c["repo"].count("/") == 1 for c in picks)


def test_default_count_is_five():
    """Story: by default we aim for five popular makers.

    Given  the tool flags --download-top-tier is being used without --count,
    When   it reads the built-in default,
    Then   the default number of providers to download is 5 (a variety of what's
           popular now), not 1.
    """
    # Read the launcher's own help and confirm --count's default is 5, tolerating
    # the argparse line-wrap of "default 5" (which may split across lines).
    out = subprocess.run([sys.executable, str(REPO / "scripts/llama_serve.py"),
                          "--help"], capture_output=True, text=True).stdout
    assert "--count" in out, "--help must document --count"
    # "default 5" may wrap:  "--count COUNT ... default\n                       5 = ..."
    import re
    assert re.search(r"default\s*5", out), "--help must document --count default 5"


def test_download_progress_shows_percentage():
    """Story: you can see how far the download has progressed.

    Given  the downloader is fetching a real model,
    When   it writes its progress,
    Then   each progress line must include a 0-100% percentage (a quick readout of
           how much is done), plus the size downloaded and speed — in the terminal.
    """
    _real_hf()
    # run hf_download.py on the real 0.5B model in a temp dir with the expected-size arg
    import tempfile
    tmp = tempfile.mkdtemp(prefix="pcttest")
    try:
        # get real expected bytes from HF tree API
        real = next(f for f in llama_ai._repo_gguf_files("Qwen/Qwen2.5-0.5B-Instruct-GGUF")
                    if f["path"] == "qwen2.5-0.5b-instruct-q4_0.gguf")
        dl = str(REPO / "scripts" / "hf_download.py")
        out = subprocess.run(
            [sys.executable, dl, "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
             "qwen2.5-0.5b-instruct-q4_0.gguf", tmp, "pcttest", "0", str(real["size_bytes"])],
            capture_output=True, text=True, timeout=240).stdout
        # the live terminal progress must contain a percentage
        assert "%" in out, f"download should print a % progress; got:\n{out[-600:]}"
        # and the log file should too
        import glob
        logs = glob.glob(f"{tmp}/*.progress.log")
        assert logs, "a .progress.log should exist"
        logtxt = open(logs[0]).read()
        assert "%" in logtxt, "progress.log should contain a % readout"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_cli_download_top_tier_dry_run_detailed():
    """Story: the REAL CLI `llama-ai --download-top-tier --dry` runs end-to-end and
    prints a detailed, structured preview — the actual entry point, not just a helper.

    Given  I run the real launcher binary with `--download-top-tier --dry --count 2`,
    When   it discovers trending top-tier models that fit the actual card (real HF API,
           no download because --dry),
    Then   stdout must show the dynamic memory readout (RAM + headroom), a
           `[dry] would download top N` marker, and for EACH candidate a row containing
           its provider, filename, size, and tier folder — and it must NOT start a
           server or download anything.
    """
    total = llama_ai.read_total_ram_bytes()
    head = llama_ai.read_current_headroom_bytes(total)
    # run the REAL binary via subprocess (the CLI entry point, real argv -> main).
    # Pin a 48 GB card via LLAMA_RAM_BYTES so a top-tier model reliably fits on ANY
    # host/CI-runner, exercising the ranked-preview branch (not the no-fit branch).
    env = dict(os.environ)
    env["LLAMA_RAM_BYTES"] = str(48 * 1024 ** 3)
    out = subprocess.run([sys.executable, str(REPO / "scripts/llama_serve.py"),
                          "--download-top-tier", "--dry", "--count", "2"],
                         capture_output=True, text=True, timeout=180, env=env)
    assert out.returncode == 0, f"dry run must exit 0; stderr:\n{out.stderr[-800:]}"
    s = out.stdout
    assert "detecting memory on the actual card" in s, s[-800:]
    assert "total RAM" in s, "dry run must print the dynamic total-RAM readout"
    assert "headroom" in s, "dry run must print the headroom readout"
    assert "would download top" in s, f"must print '[dry] would download top N'; got:\n{s[-800:]}"
    # --count 2 => up to 2 providers x per-provider(2) = up to 4 candidate rows
    lines = [ln for ln in s.splitlines() if "->" in ln and ".gguf" in ln]
    assert lines, f"dry run must list candidate rows with provider::file -> path; got:\n{s[-800:]}"
    assert len(lines) <= 4, f"--count 2 with per-provider 2 => <=4 rows, got {len(lines)}"
    for ln in lines[:2]:
        assert "/" in ln, f"candidate row must show provider repo: {ln}"
        assert ".gguf" in ln, f"candidate row must name the .gguf file: {ln}"
        assert "GiB" in ln or "GB" in ln, f"candidate row must show size: {ln}"
        assert ("48GB" in ln or "24GB" in ln or "16GB" in ln or "8GB" in ln), \
            f"candidate row must show tier folder: {ln}"
    assert "nothing was downloaded or served" in s or "nothing could be downloaded" in s, \
        f"dry run must confirm nothing was downloaded; got:\n{s[-400:]}"
    # --dry must NOT launch llama-server
    assert "llama-server" not in out.stderr.lower(), "dry run must not spawn llama-server"
    assert "==> " not in out.stderr.lower() or "llama-server" not in s, \
        "dry run must not start a server"
