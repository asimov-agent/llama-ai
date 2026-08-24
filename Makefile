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
PY      := $(VENV)/bin/python
LAUNCHER := $(BIN)/llama-ai
# llama.cpp llama-server binary — symlinked into ~/bin so llama_ai.py resolves
# it as `llama-server` on PATH. Override if built elsewhere.
LLAMA_SERVER_BIN ?= $(HOME)/repository/git/llama.cpp/build/bin/llama-server

.PHONY: all install venv-install link uninstall smoke list version help \
	openspec-image openspec-new openspec-validate openspec-status openspec-shell \
	test test-unit test-install test-health download-test-model \
	loop loop-harness chained

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
	@echo "Symlink: $(BIN)/llama_ai.py -> $(REPO)/llama_ai.py"

# ---- 1. build the gguf-tooling venv (Python 3.10 + gguf + numpy) --------
venv-install:
	@echo "==> Building gguf venv at $(VENV)"
	$(MAKE) -C tools venv-install

# ---- 2+3. launcher wrapper + symlink into ~/bin -------------------------
link:
	@mkdir -p "$(BIN)"
	@printf '#!/usr/bin/env bash\n# llama-ai launcher -> runs %s with the %s venv.\n# Prepend ~/bin to PATH so the llama-server symlink there resolves in any shell.\nexport PATH="$(BIN):$$PATH"\nexec "%s" "%s/llama_ai.py" "$$@"\n' \
		"$(REPO)/llama_ai.py" "$(VENV)" "$(PY)" "$(REPO)" > "$(LAUNCHER)"
	@chmod +x "$(LAUNCHER)"
	@ln -sfn "$(REPO)/llama_ai.py" "$(BIN)/llama_ai.py"
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

openspec-status: ## openspec status
	$(RUNTIME) run $(OS_OPTS) openspec status

openspec-shell: ## Interactive shell into the repo with the openspec CLI
	$(RUNTIME) run --rm -it -v "$(REPO)":/repo:rw -w /repo $(OS_IMG) /bin/sh

# ---- Tests (pytest suite under the gguf venv python) -------------------------------
test-unit: ## Hermetic unit tests for llama_ai.py (no ~/bin/~/models needed)
	"$(PY)" -m pytest tests/test_llama_ai.py -p no:cacheprovider -q

test-install: ## Host install tests (verify installed ~/bin/llama-ai runs a model)
	"$(PY)" -m pytest tests/test_install.py -p no:cacheprovider -q

test-health: ## End-to-end health check: launch tiny model, answer 'hi' on the endpoint
	"$(PY)" -m pytest tests/test_health.py -p no:cacheprovider -q -s

test: ## Full fast suite (unit + install; health check not included — run test-health separately)
	"$(PY)" -m pytest tests/test_llama_ai.py tests/test_install.py -p no:cacheprovider -q

download-test-model: ## Fetch the lightweight (0.5B Q4 ~340MB) health-check model into ~/models/Qwen/8GB
	"$(PY)" scripts/download_test_model.py

loop: loop-harness ## alias
loop-harness: ## Loop runner: download-test-model -> unit -> install -> health -> test -> openspec-validate
	"$(PY)" scripts/loop_harness.py

# Run every verification step explicitly (Makefile-level chain, same order as
# loop-harness). Fails fast on the first failing step.
chained: test-unit test-install test-health test openspec-validate
	@echo "All chain steps completed."

uninstall: ## Remove the launcher + symlinks (leaves the venv)
	@rm -f "$(LAUNCHER)" "$(BIN)/llama_ai.py" "$(BIN)/llama-server"
	@echo "Removed $(LAUNCHER), $(BIN)/llama_ai.py, and $(BIN)/llama-server"
	@echo "(venv kept at $(VENV); 'make -C tools clean' to drop requirements.txt)"

help:
	@echo "Targets:" \
		"install (venv+launcher+symlink+smoke), venv-install, link, smoke,"
	@echo "         test-unit, test-install, test-health (endpoint answers 'hi'), test,"
	@echo "         download-test-model, openspec-validate, openspec-new/status,"
	@echo "         loop (chained runner), loop-harness, chained, uninstall"