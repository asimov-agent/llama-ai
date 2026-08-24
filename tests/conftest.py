"""Shared pytest fixtures for the llama-ai test suite.

All tests run under the gguf venv python (see Makefile `test` target). We
expose the repo root so tests can locate llama_ai.py / Makefile / tools.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Repo root = parent of this tests/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import llama_ai  # noqa: E402  (importable: gguf+numpy come from the venv)

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