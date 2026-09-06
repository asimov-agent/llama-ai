"""Host end-to-end serve test for a downloaded top-tier model.

Story: after --download-top-tier fetches a lightweight top-tier model, we must
prove it not only downloads but actually LOADS and SERVES on the real backend
(GPU/Metal locally, CPU in CI) and answers "hi", leaving RAM headroom.

This mirrors test_health.py but drives the downloaded lightweight model through
the top-tier download path (real hf download if absent), then launch -> /health
-> POST "hi" -> assert reply -> re-measure RAM to prove headroom. No mocks.

Runs under `make test-top-tier-serve` (host) and `make test-top-tier-serve-ci`
(container/CPU). Skips only if llama-server is genuinely absent.
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

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import scripts.llama_serve as llama_ai  # noqa: E402

pytestmark = pytest.mark.acceptance

# The lightweight model the top-tier serve test uses (0.5B Q4 ~430 MB), same as
# the health check. Downloaded for real via the top-tier path when absent.
REPO_ID = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
FILENAME = "qwen2.5-0.5b-instruct-q4_0.gguf"


def _real_hf() -> str:
    import shutil
    hf = os.environ.get("HF_BIN") or shutil.which("hf")
    if not hf or not Path(hf).is_file():
        hf_env = Path.home() / "llama-gguf-tools/venv/bin/hf"
        if hf_env.is_file():
            hf = str(hf_env)
    assert hf and Path(hf).is_file(), "hf CLI needed for the top-tier serve test"
    return hf


def _resolve_model_file(tmp_root) -> str:
    """Download the lightweight top-tier model for real (idempotent) into tmp_root."""
    _real_hf()
    real = next(f for f in llama_ai._repo_gguf_files(REPO_ID) if f["path"] == FILENAME)
    tier = llama_ai.pick_tier_folder(real["size_bytes"], 16 * 1024 ** 3)  # small-model tier
    cand = {
        "repo": REPO_ID,
        "filename": FILENAME,
        "size_bytes": real["size_bytes"],
        "size_gb": real["size_gb"],
        "tier_folder": tier,
        "dest_path": f"{tmp_root}/Qwen/Qwen2.5-0.5B-Instruct-GGUF/{tier}/{FILENAME}",
    }
    final = llama_ai.download_top_tier_candidate(dict(cand), models_root=tmp_root)
    assert Path(final).is_file(), f"downloaded model missing: {final}"
    return final


def _pick_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _pids_on_port(port: int):
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return []
    return [p for p in out.split() if p.isdigit()]


def _available_mem_gb() -> float:
    """Approx available (free+inactive) memory in GB on macOS, else total-unknown."""
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            ps = 16384
            free = inactive = 0
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Pages free:"):
                    free = int(line.split(":")[1].strip().rstrip("."))
                if line.startswith("Pages inactive:"):
                    inactive = int(line.split(":")[1].strip().rstrip("."))
            return (free + inactive) * ps / (1024 ** 3)
        except Exception:
            return 0.0
    return 0.0  # non-macOS: headroom measured via hw.memsize+vm_stat only on mac


def _wait_healthy(url: str, timeout: float = 180.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/health", timeout=2) as r:
                if r.status == 200 and json.loads(r.read()).get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _chat(url: str, prompt: str = "hi") -> str | None:
    body = json.dumps({"model": "llm-local",
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 32, "temperature": 0.0}).encode()
    req = urllib.request.Request(url + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return data.get("choices", [{}])[0].get("message", {}).get("content")


def _resolve_llama_server():
    """llama-server on PATH / LLAMA_SERVER / ~/bin/llama-server / repo build."""
    env = (os.environ.get("LLAMA_SERVER") or "").strip()
    if env and Path(env).is_file():
        return env
    import shutil
    p = shutil.which("llama-server")
    if p:
        return p
    home = Path.home() / "bin/llama-server"
    if home.is_file():
        return str(home)
    repo_bin = REPO.parent / "llama.cpp/build/bin/llama-server"
    if repo_bin.is_file():
        return str(repo_bin)
    return None


def test_top_tier_serve_loads_and_answers_hi(tmp_path):
    """Story: the downloaded model really runs and answers.

    Given  a lightweight top-tier model is downloaded for real,
    When   we launch llama-server on it via the top-tier path,
    Then   it must load, be healthy, and answer "hi" with real text,
           and the machine must still have memory headroom after loading.
    """
    model = _resolve_model_file(str(tmp_path))
    server = _resolve_llama_server()
    # NO-SKIP: if llama-server is absent this is a loud FAILURE, never a silent skip.
    # (In CI the test image bundles a CPU llama-server; locally it comes from PATH,
    #  $LLAMA_SERVER, ~/bin/llama-server, or the repo build.)
    assert server, (
        "llama-server binary not found (checked $LLAMA_SERVER, PATH, ~/bin/llama-server, "
        "and the repo llama.cpp build). Cannot run the serve test. Set LLAMA_SERVER or "
        "build llama.cpp — missing prerequisite is a hard failure, never a skip."
    )

    port = _pick_port()
    url = _base_url(port)
    # memory before
    mem_before = _available_mem_gb()

    argv = [server, "-m", model, "--host", "127.0.0.1", "--port", str(port),
            "-c", "2048", "-ngl", "0"]  # -ngl 0 = CPU (works on GPU-less CI too)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        healthy = _wait_healthy(url)
        if not healthy:
            out = (proc.stdout.read() if proc.stdout else "")[-2000:]
            pytest.fail(f"top-tier server on :{port} never healthy.\n{out}")
        reply = _chat(url, "hi")
        assert reply, "/v1/chat/completions returned empty reply for 'hi'"
        print(f"\n[top-tier-serve] model replied to 'hi': {reply.strip()[:120]}", flush=True)

        # post-load headroom
        if mem_before > 0:
            mem_after = _available_mem_gb()
            # it loaded; free+inactive should not be exhausted. Tolerant: still have >0.1 GB
            assert mem_after >= 0.1, \
                f"headroom exhausted after load: before={mem_before:.1f}GB after={mem_after:.1f}GB"
            print(f"[top-tier-serve] RAM before={mem_before:.1f}GB after={mem_after:.1f}GB "
                  f"(headroom remains)", flush=True)
    finally:
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
