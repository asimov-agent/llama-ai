"""Hermetic e2e tests for the stall-watch fix in scripts/hf_download.py (issue #55).

NO MOCKS: each test drives the REAL hf_download.main() as a subprocess against a REAL
fake-`hf` executable (tests/fixtures/fake_hf.py) that is a genuine child process
writing real bytes to a real temp dir. `tree_bytes` reads the real disk. The stall
threshold and poll interval are shrunk via env (HF_STALL_SECONDS / HF_POLL_SECONDS)
so the runs finish fast; production defaults stay at 90s / 3s.
"""
from __future__ import annotations

import os, subprocess, sys, time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HF_DL = ROOT / "scripts" / "hf_download.py"
FAKE_HF = HERE / "fixtures" / "fake_hf.py"


def _run(tmp: Path, mode: str, stall_seconds: float = 90, poll: float = 3) -> dict:
    """Execute the REAL hf_download.main() with HF_BIN -> the fake hf, in `mode`.

    Returns {"rc", "log_text", "attempts"} parsed from the .progress.log.
    """
    dest = tmp / "dest"
    dest.mkdir(parents=True)
    env = dict(os.environ)
    env["HF_BIN"] = str(FAKE_HF)
    env["FAKE_HF_MODE"] = mode
    env["HF_STALL_SECONDS"] = str(stall_seconds)
    env["HF_POLL_SECONDS"] = str(poll)
    env["HF_RETRY_PAUSE"] = "0.1"
    env["HF_MAX_RETRY"] = "2"   # keep the stall test's retry loop short/fast
    env.pop("HF_TOKEN", None)          # hermetic: never hit the Hub
    env.pop("HF_XET_HIGH_PERFORMANCE", None)
    label = f"test-{mode}"
    proc = subprocess.run(
        [sys.executable, str(HF_DL), "fake/repo", "model.gguf", str(dest), label, "1", "131072"],
        env=env, capture_output=True, text=True, timeout=120,
    )
    log = (dest / f"{label}.progress.log")
    log_text = log.read_text() if log.exists() else ""
    # attempts = number of "=== attempt N (" blocks started
    attempts = log_text.count("=== attempt ")
    return {"rc": proc.returncode, "log_text": log_text, "attempts": attempts}


def test_stalled_download_is_killed_and_retried(tmp_path):
    """A still-alive download with no forward progress must be terminated and retried.

    # Given a fake `hf` in FAKE_HF_MODE=stall (writes bytes once then sits at 0),
    # When  hf_download.main() runs with a tiny stall threshold (6s) + fast poll,
    # Then  the subprocess is killed (rc!=0 -> retry),
    # And   the log records at least one STALLED line,
    # And   a second attempt is started.
    """
    r = _run(tmp_path, "stall", stall_seconds=6, poll=0.2)
    assert "STALLED" in r["log_text"], r["log_text"]
    assert r["attempts"] >= 2, r["log_text"]
    # rc is eventually non-zero/failed because the fake never completes => will return 1
    assert r["rc"] == 1, r["log_text"]


def test_healthy_download_never_stalled(tmp_path):
    """A growing download must never be spuriously terminated.

    # Given a fake `hf` in FAKE_HF_MODE=grow (appends bytes continuously),
    # When  hf_download.main() runs with the same small stall threshold + fast poll,
    # Then  the subprocess completes on attempt 1 (rc=0),
    # And   NO 'STALLED' line appears,
    # And   only one attempt is recorded.
    """
    r = _run(tmp_path, "grow", stall_seconds=6, poll=0.2)
    assert r["rc"] == 0, r["log_text"]
    assert "STALLED" not in r["log_text"], r["log_text"]
    assert r["attempts"] == 1, r["log_text"]


def test_stall_decision_helper_semantics():
    """The pure stall-decision helper follows the advancing-marker contract.

    # Given a helper `_stall_decision(total, last_bytes, last_advancing, now)`,
    # When  total grows,            Then it resets the advancing clock and stalled_for=0.
    # When  total does not grow,    Then stalled_for = now - last_advancing (accumulates).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("hf_dl", str(HF_DL))
    assert spec and spec.loader, "cannot load hf_download.py for hard import"
    hd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hd)

    # GIVEN total grew since last_bytes
    la, sf = hd._stall_decision(total=100, last_bytes=50, last_advancing=10.0, now=30.0)
    assert la == 30.0
    assert sf == 0.0

    # GIVEN total unchanged, launch 130s after the last advance (threshold=90)
    la, sf = hd._stall_decision(total=100, last_bytes=100, last_advancing=10.0, now=130.0)
    assert la == 10.0
    assert sf == 120.0


# silence "unused fixture" warnings; nothing skipped
print = pytest