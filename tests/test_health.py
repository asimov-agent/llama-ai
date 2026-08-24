"""Host end-to-end health check for llama-ai.

Part of the loop harness (`make loop` -> `health` stage). Verifies the
installed entry point works by actually running a model and answering a prompt:

  1. locate the lightweight test model under ~/models (it must already be
     downloaded into the right GPU tier — run `make download-test-model`);
  2. launch `$HOME/bin/llama-ai` (the installed launcher) on a random high port
     so it never clashes with a user server already on 11434;
  3. poll GET /health until the server reports ready;
  4. POST a prompt ("hi") to /v1/chat/completions and assert we get a text
     completion back => the serving endpoint is healthy end-to-end.

Skips cleanly (does not error) if the model or llama-server is absent, so the
loop stays green on a host that has not downloaded the test model yet.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from conftest import BIN, MODELS_ROOT

pytestmark = pytest.mark.health

# The lightweight model the health check uses (0.5B Q4 ~340-430 MB). It lives
# in the 8GB GPU tier. Substring used to select it via the launcher.
HEALTH_MODEL = "0.5b"
HEALTH_TIER = MODELS_ROOT / "Qwen" / "8GB"
MODEL_FILE = HEALTH_TIER / "qwen2.5-0.5b-instruct-q4_0.gguf"

LAUNCHER = BIN / "llama-ai"           # installed wrapper (runs llama_ai.py w/ venv py)


def _pick_port() -> int:
    """Return a likely-free high port for the ephemeral server."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _pids_on_port(port: int) -> list[str]:
    """Return PIDs listening on the given TCP port (lsof-based, best-effort)."""
    try:
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return []
    return [p for p in out.split() if p.isdigit()]


def _wait_healthy(url: str, timeout: float = 180.0) -> bool:
    """Poll GET /health until it returns JSON status ok (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/health", timeout=2) as r:
                if r.status == 200:
                    try:
                        if json.loads(r.read()).get("status") == "ok":
                            return True
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(2)
    return False


def _chat(url: str, prompt: str = "hi") -> str | None:
    """Send a chat completion request; return the assistant text or None."""
    body = json.dumps({
        "model": "llm-local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32,
        "temperature": 0.0,
    }).encode()
    req = urllib.request.Request(
        url + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return data.get("choices", [{}])[0].get("message", {}).get("content")


@pytest.mark.skipif(
    not MODEL_FILE.is_file() or not LAUNCHER.is_file(),
    reason="lightweight test model or llama-ai launcher not installed",
)
def test_health_endpoint_answers_hi():
    # The launcher stops anything it finds on the chosen port, so a random high
    # port keeps the user's own server (11434) untouched.
    port = _pick_port()
    url = _base_url(port)

    # Launch the INSTALLED launcher from the ~/bin directory (the exact host
    # install path the user/loop cares about). It resolves llama-server itself.
    log = MODEL_FILE.parent / ".run.log"
    proc = subprocess.Popen(
        [str(LAUNCHER), HEALTH_MODEL, "--port", str(port)],
        cwd=str(BIN),          # run it from ~/bin, as installed
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        # 1. wait for a healthy endpoint
        healthy = _wait_healthy(url)
        if not healthy:
            out = (proc.stdout.read() if proc.stdout else "")[-2000:]
            pytest.fail(
                f"server on :{port} never became healthy. log={log}\nlauncher output:\n{out}"
            )
        # 2. send "hi" and expect a real completion
        reply = _chat(url, "hi")
        assert reply, f"/v1/chat/completions returned empty reply for 'hi'"
        # 3. log the actual reply so the loop shows the model answered.
        print(f"\n[health] model replied to 'hi': {reply.strip()[:120]}", flush=True)
    finally:
        # Terminate the launcher AND kill any llama-server it spawned on that
        # port (the wrapper `exec`s into python -> subprocess.run(llama-server),
        # so terminating the wrapper does not always reap the child server).
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        for pid in _pids_on_port(port):
            try:
                os.kill(int(pid), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass
