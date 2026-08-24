# llama-ai test container: runs every verification stage containerized so the
# same stages run identically on the dev host (nerdctl/colima) and in CI (docker).
#
#   make test-image        # build
#   make lint / test-unit / test-install / test-health   # any stage
#
# Fully self-contained: it bundles python + pytest + deps AND a CPU-only
# llama-server (built in-image), so `test-health` launches the model with no
# external binary — identical on every host.
FROM python:3.10-slim AS base

# Runtime + test deps (copied from the repo's compiled lockfiles at build).
# These are regenerated from tools/requirements.in + tools/requirements-dev.in
# (source of truth), never hand-edited.
COPY requirements.txt requirements-dev.txt /tmp/
RUN pip install --no-cache-dir \
        -r /tmp/requirements.txt \
        -r /tmp/requirements-dev.txt \
        # `hf` cloud-download CLI (huggingface_hub), used by download_test_model.py
        # with resume/retry. Must be on PATH in the container so the same
        # download command works on CI as on the host.
        "huggingface_hub[cli]>=0.30"

# curl for the health probe; git for diagnostics (linefeed lint uses git ls-files);
# build toolchain for llama-server.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git build-essential cmake \
    && rm -rf /var/lib/apt/lists/* \
    # the repo is bind-mounted from the host (owned by a different uid); mark it
    # safe so `git ls-files` in the lint stage works as root in the container.
    && git config --global --add safe.directory '*'

# ---- Build a CPU-only llama-server into the image --------------------------
# GitHub Actions runners (and this container) have no GPU, so we build pure CPU.
# This is what makes the `health` stage a REAL cpu-llm check that runs anywhere.
RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp \
    && cmake -S /tmp/llama.cpp -B /tmp/llama.cpp/build -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_CUBLAS=OFF -DGGML_CUDA=OFF -DLLAMA_METAL=OFF -DGGML_METAL=OFF \
        -DLLAMA_CURL=OFF \
    && cmake --build /tmp/llama.cpp/build --config Release -j2 --target llama-server \
    && install -m 0755 /tmp/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server \
    && rm -rf /tmp/llama.cpp

WORKDIR /repo

# llama-server is on PATH; llama_ai.py resolves it (LLAMA_SERVER unset -> PATH).
ENV LLAMA_SERVER=
CMD ["--help"]