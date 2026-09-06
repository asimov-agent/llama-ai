"""Shared pytest fixtures for the llama-ai test suite.

All tests run under the gguf venv python (see Makefile `test` target). We
expose the repo root so tests can locate scripts/llama_serve.py / Makefile / tools.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Repo root = parent of this tests/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.llama_serve as llama_ai  # noqa: E402  (importable: gguf+numpy come from the venv)

HOME = Path.home()
MODELS_ROOT = HOME / "models"
BIN = HOME / "bin"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def launcher() -> Path:
    """Executable ~/bin/llama-ai installed by `make install`."""
    return BIN / "llama-ai"


@pytest.fixture(scope="session")
def models_root() -> Path:
    return MODELS_ROOT


@pytest.fixture(scope="session")
def server_bin() -> str:
    """llama-server binary (resolved via PATH or LLAMA_SERVER)."""
    # reads the env the same way llama_ai.resolve_llama_server does, but
    # tolerates absence so we can assert the right error message in tests.
    env = (os.environ.get("LLAMA_SERVER") or "").strip()
    if env and Path(env).is_file():
        return env
    import shutil
    return shutil.which("llama-server") or ""


# ---------------------------------------------------------------------------
# NO-SKIP GUARD (mandatory): a skipped test is a LOUD FAILURE, never silent.
# This is the durable "no skips ever" guarantee — any test that calls
# pytest.skip()/skipif() (or is skipped for any reason) turns the run red so a
# broken/absent prerequisite can never silently pass CI. See AGENTS.md.
# ---------------------------------------------------------------------------
def pytest_report_teststatus(report, config):
    if getattr(report, "skipped", False):
        # Mark a skipped test as a failure in the exit code (loud), not silent.
        report.outcome = "failed"
        report.longrepr = (
            "TEST SKIPPED — no skips allowed (AGENTS.md). A skipped test means a "
            "broken prerequisite is being masked. Provision the prerequisite (e.g. "
            "run `make download-test-model` / `make install` / set LLAMA_SERVER) so "
            "the test genuinely runs, or fix the test — never leave a skip."
        )
    return None


def pytest_runtest_logreport(report):
    if report.when == "call" and getattr(report, "skipped", False):
        # Convert a (non-xfail) skip into a hard failure right at the call site.
        if not getattr(report, "wasxfail", False):
            report.outcome = "failed"
            report.longrepr = (
                "TEST SKIPPED — no skips allowed (AGENTS.md). A skipped test masks a "
                "broken prerequisite. Provision it (make download-test-model / make "
                "install / LLAMA_SERVER) so the test runs — never leave a skip."
            )
