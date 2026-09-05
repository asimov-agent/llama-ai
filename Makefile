# llama-ai install Makefile.
#
# `make install` does the WHOLE setup so you never touch the venv manually:
#   1. builds the Python 3.10 gguf-tooling venv (./tools/venv-install)
#   2. writes a runnable launcher `~/bin/llama-ai` that executes `llama_ai.py`
#      with the venv's python (so `gguf`/`numpy` resolve without extra steps)
#   3. symlinks `~/bin/llama_ai.py` -> this repo's `llama_ai.py`
#   4. verifies the install with a `--list` smoke run
#
# After `make install` you can simply run:
#       llama-ai                 # interactive picker
#       llama-ai --list          # list models
#       llama-ai qwen            # launch by substring
#       llama-ai --dry qwen      # print the tuned command, don't run

SHELL   := /bin/bash
HOME    := $(shell printf '%s' "$$HOME")
BIN     := $(HOME)/bin
# Put ~/bin on PATH for every recipe so `llama-server` (symlinked there by
# `make install`) resolves even in non-interactive make subprocesses — not just
# in an interactive zsh that sourced ~/.zshrc.
export PATH := $(BIN):$(PATH)
REPO    := $(shell pwd)
VENV    := $(HOME)/llama-gguf-tools/.venv
# Prefer the venv python (host install) but fall back to a plain `python3`
# when the venv is absent — e.g. a bare GitHub Actions runner. This lets the
# same Makefile test/lint targets run identically on the host and in CI.
PY      := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
LAUNCHER := $(BIN)/llama-ai
# llama.cpp llama-server binary — symlinked into ~/bin so llama_ai.py resolves
# it as `llama-server` on PATH. Override if built elsewhere.
LLAMA_SERVER_BIN ?= $(HOME)/repository/git/llama.cpp/build/bin/llama-server

.PHONY: all install venv-install link uninstall smoke list version help \
	openspec-image openspec-new openspec-validate openspec-status openspec-shell \
	test test-unit test-install test-health download-test-model \
	test-image test-clean lint lint-fix loop loop-harness chained

# ---- container runtime (nerdctl preferred, docker fallback) --------------
RUNTIME ?= nerdctl
ifeq ($(shell command -v $(RUNTIME) >/dev/null 2>&1 && echo yes),)
RUNTIME = docker
endif
OS_IMG := llama-ai/openspec:latest

all: install

# ---- full install: venv + launcher + symlink + smoke test --------------
install: venv-install link smoke
	@echo
	@echo "Installed. Run '$(LAUNCHER)' (e.g. 'llama-ai --list', 'llama-ai qwen')."
	@echo "Symlink: $(BIN)/llama_ai.py -> $(REPO)/scripts/llama_serve.py"

# ---- 1. build the gguf-tooling venv (Python 3.10 + gguf + numpy) --------
venv-install:
	@echo "==> Building gguf venv at $(VENV)"
	$(MAKE) -C tools venv-install

# ---- 2+3. launcher wrapper + symlink into ~/bin -------------------------
link:
	@mkdir -p "$(BIN)"
	@printf '#!/usr/bin/env bash\n# llama-ai launcher -> runs %s with the %s venv.\n# Prepend ~/bin to PATH so the llama-server symlink there resolves in any shell.\nexport PATH="$(BIN):$$PATH"\nexec "%s" "%s" "$$@"\n' \
		"$(REPO)/scripts/llama_serve.py" "$(VENV)" "$(PY)" "$(REPO)/scripts/llama_serve.py" > "$(LAUNCHER)"
	@chmod +x "$(LAUNCHER)"
	@ln -sfn "$(REPO)/scripts/llama_serve.py" "$(BIN)/llama_ai.py"
	@if [ -x "$(LLAMA_SERVER_BIN)" ]; then \
		ln -sfn "$(LLAMA_SERVER_BIN)" "$(BIN)/llama-server"; \
		echo "==> Symlinked ~/bin/llama-server -> $(LLAMA_SERVER_BIN)"; \
	else \
		echo "WARN: llama-server binary not found at $(LLAMA_SERVER_BIN)." >&2; \
		echo "      llama_ai.py will terminate until 'llama-server' is on PATH." >&2; \
		echo "      Set LLAMA_SERVER_BIN=<path> or add llama-server to PATH." >&2; \
	fi
	@echo "==> Wrote $(LAUNCHER) (exec) and symlinked ~/bin/llama_ai.py -> repo"

# ---- 4. smoke: confirm the launcher can list models ---------------------
smoke:
	@echo "==> Smoke test: $(LAUNCHER) --list"
	@$(LAUNCHER) --list || { echo "Installed, but model scan returned nothing (no .gguf under ~/models yet), or gguf import failed." >&2; exit 1; }

# ---- helpers ------------------------------------------------------------
list:
	@$(LAUNCHER) --list

generate-requirements: ## Recompile tools/requirements.in -> tools/requirements.txt (container or venv pip-compile)
	$(MAKE) -C tools generate-requirements

version: ## Show numpy/gguf versions inside the venv
	$(MAKE) -C tools version

# ---- OpenSpec (Dockerized CLI) --------------------------------------------
# The OpenSpec CLI runs inside the openspec/ container with the repo mounted at
# /repo, so `make openspec-new` etc. create/validate openspec/changes/<name> in
# this repository. This is the checklist-of-record for agent work: every step
# you implement maps to a task in openspec/changes/<name>/tasks.md.

openspec-image: ## Build the OpenSpec CLI container
	$(RUNTIME) build -t $(OS_IMG) openspec/
	@echo "OpenSpec image built: $(OS_IMG)"

OS_OPTS := --rm -u root -v "$(REPO)":/repo:rw -w /repo $(OS_IMG)

openspec-new: openspec-image ## openspec new change <NAME>
	@test -n "$(NAME)" || { echo "Usage: make openspec-new NAME=<kebab-name>"; exit 1; }
	$(RUNTIME) run $(OS_OPTS) openspec new change $(NAME)

openspec-validate: ## openspec validate <NAME>  (fail-closed gate used by the loop)
	@test -n "$(NAME)" || { echo "Usage: make openspec-validate NAME=<change>"; exit 1; }
	$(RUNTIME) run $(OS_OPTS) openspec validate $(NAME)

openspec-tasks-check: ## Assert all ACTIVE OpenSpec changes have no unchecked task checkboxes (NAME=<change> to check one). Fails CI when a task is left `- [ ]`. Pure-python host-side (no container needed).
	@python3 scripts/check_openspec_tasks.py $(NAME)

openspec-status: ## openspec status
	$(RUNTIME) run $(OS_OPTS) openspec status

openspec-shell: ## Interactive shell into the repo with the openspec CLI
	$(RUNTIME) run --rm -it -v "$(REPO)":/repo:rw -w /repo $(OS_IMG) /bin/sh

# ---- Tests (containerized — run identically on host nerdctl and CI docker) --
# The test image bundles python + pytest + all deps; the repo is mounted at
# /repo and llama-server is resolved via $LLAMA_SERVER (host LLAMA_BIN or CI
# build). Bare `run` (like the openspec targets) avoids compose's `--tty`
# console requirement under non-interactive make.
TEST_IMG := llama-ai/test:latest
TEST_OPTS := --rm -u root -v "$(REPO)":/repo:rw -w /repo -e HOME=/root
TEST_RUN := $(RUNTIME) run $(TEST_OPTS) $(TEST_IMG)

test-image: ## Build the containerized test image (copies compiled requirements into context)
	@cp tools/requirements.txt tools/requirements-dev.txt containers/test/
	$(RUNTIME) build -t $(TEST_IMG) containers/test/
	@echo "Test image built: $(TEST_IMG)"

test-clean: ## Remove left-over/stopped orphaned containers of the test image (interrupted/failed runs)
	# Docker/nerdctl-agnostic: list all containers referencing the test image
	# (name format is <random>-test-id), stop+remove ONLY the stopped/left-over
	# ones -- never kill a currently-running test (e.g. an in-progress health
	# check). Never uses `--filter ancestor` (docker lacks it).
	@containers=$$($(RUNTIME) ps -a -q 2>/dev/null); \
	for c in $$containers; do \
	  info=$$($(RUNTIME) inspect -f '{{.Image}}' $$c 2>/dev/null || echo ""); \
	  if printf '%s' "$$info" | grep -q "llama-ai/test"; then \
	    running=$$($(RUNTIME) inspect -f '{{.Running}}' $$c 2>/dev/null || echo "false"); \
	    if printf '%s' "$$running" | grep -qi "false"; then \
	      $(RUNTIME) rm -f $$c 2>/dev/null; \
	    fi; \
	  fi; \
	done; \
	echo "Pruned stopped orphaned $(TEST_IMG) containers."

test-unit: ## Hermetic unit tests (containerized) — includes the lint regression test
	$(TEST_RUN) python -m pytest tests/test_llama_ai.py tests/test_lint_linefeeds.py tests/test_watchloop_dispatch.py -p no:cacheprovider -q

test-agents-read: ## Guard: AGENTS.md must not match Hermes context-file threat patterns (fail-closed). Host-side: uses a Python >=3.11 that has hermes-agent installed (3rd-party PyPI dep, pinned ==0.19.0; the CI agents-read job installs it itself). Not containerized, to avoid bumping the 3.10 test image.
	@echo "==> test-agents-read: scanning AGENTS.md with the installed hermes-agent threat scanner"
	@AR=; for py in python3.12 python3.11; do \
	  if command -v $$py >/dev/null 2>&1 && $$py -c "import tools.threat_patterns" 2>/dev/null; then AR=$$py; break; fi; \
	done; \
	if [ -z "$$AR" ]; then \
	  echo "ERROR: no Python >=3.11 with hermes-agent installed found. Run 'pip install hermes-agent==0.19.0' into a Python >=3.11 interpreter (the CI agents-read job does this automatically)."; \
	  exit 1; \
	fi; \
	echo "  using $$AR"; \
	$$AR scripts/scan_agents_md.py AGENTS.md

test-install: ## Host install tests (containerized) — skips cleanly without artifacts
	$(TEST_RUN) python -m pytest tests/test_install.py -p no:cacheprovider -q

test-install-host: ## Verify the REAL host install (make install) — runs on the host where ~/bin/llama-ai + ~/models exist
	# Runs tests/test_install.py with the gguf venv python on the HOST, so the
	# actual `make install` artifacts (~/bin/llama-ai launcher, symlinks,
	# ~/bin/llama-server, ~/models) are asserted — not skipped. This is the
	# local/AGENTS.md proof that `make install` works.
	@echo "==> Verifying host install artifacts via tests/test_install.py"
	@$(PY) -m pytest tests/test_install.py -p no:cacheprovider -q

test-top-tier: ## REAL top-tier acceptance (no mocks): live HF trending + fit gate + provider-aware download + placement
	# Host-side acceptance for --download-top-tier (issue #49): hits the live
	# Hugging Face API, the real `hf` downloader, and the real card's memory.
	# Set HF_BIN=/abs/path/to/hf when `hf` is not on PATH.
	@echo "==> Running top-tier acceptance tests (real, no mocks)"
	@HF_BIN="$${HF_BIN:-$(shell command -v hf || echo $(HOME)/models/hf-env/bin/hf)}" \
		$(PY) -m pytest tests/test_top_tier_acceptance.py -p no:cacheprovider -q -m acceptance

test-top-tier-ci: ## REAL top-tier acceptance inside the test container (CI/CPU). `hf` + gguf are bundled in the image.
	# Pin a deterministic card size (16 GB, the documented LLAMA_RAM_BYTES override) so the
	# fit gate deterministically offers top-tier models on any CI runner regardless of its
	# actual free RAM — still a REAL `hf` download, no mock. On the dev host use `test-top-tier`
	# (no pin) so it uses the real card.
	$(TEST_RUN) sh -c 'LLAMA_RAM_BYTES=17179869184 python -m pytest tests/test_top_tier_acceptance.py -p no:cacheprovider -q -m acceptance'

test-health: ## End-to-end CPU health check: ensure model, then tiny model answers 'hi' (containerized)
	$(TEST_RUN) sh -c 'python scripts/download_test_model.py && python -m pytest tests/test_health.py -p no:cacheprovider -q -s'

test: ## Full fast suite (unit + install; containerized)
	$(TEST_RUN) python -m pytest tests/test_llama_ai.py tests/test_install.py tests/test_lint_linefeeds.py -p no:cacheprovider -q

download-test-model: ## Fetch the lightweight (0.5B Q4 ~340MB) model into container ~/models/Qwen/8GB
	$(TEST_RUN) python scripts/download_test_model.py

lint: ## Linefeed lint: fail closed if any tracked text file lacks a trailing newline
	$(TEST_RUN) python scripts/lint_linefeeds.py

lint-fix: ## Append a missing trailing newline (containerized)
	$(TEST_RUN) python scripts/lint_linefeeds.py --fix

loop: loop-harness ## alias
loop-harness: ## Loop runner (host orchestration): image->download->lint->unit->install->health->test->openspec
	# The harness orchestrates the other stages by shelling out to `make`, so it
	# MUST run on the host (where make + nerdctl/docker live), NOT inside the
	# test container. It only needs python stdlib.
	@python3 scripts/loop_harness.py

# Run every verification step explicitly (Makefile-level chain, same order as
# loop-harness). Fails fast on the first failing step.
chained: test-unit test-agents-read test-install test-health test openspec-validate
	@echo "All chain steps completed."

uninstall: ## Remove the launcher + symlinks (leaves the venv)
	@rm -f "$(LAUNCHER)" "$(BIN)/llama_ai.py" "$(BIN)/llama-server" \
		"$(REPO)/scripts/llama_serve.py" "$(REPO)/scripts/hf_download.py"
	@echo "Removed $(LAUNCHER), $(BIN)/llama_ai.py, and $(BIN)/llama-server"
	@echo "(venv kept at $(VENV); 'make -C tools clean' to drop requirements.txt)"

help:
	@echo "Targets:" \
		"install (venv+launcher+symlink+smoke), venv-install, link, smoke,"
	@echo "         test-unit, test-install, test-health (endpoint answers 'hi'), test,"
	@echo "         download-test-model, openspec-validate, openspec-new/status,"
	@echo "         loop (chained runner), loop-harness, chained, uninstall"
