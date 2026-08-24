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
REPO    := $(shell pwd)
VENV    := $(HOME)/llama-gguf-tools/.venv
PY      := $(VENV)/bin/python
LAUNCHER := $(BIN)/llama-ai

.PHONY: all install venv-install link uninstall smoke list version help

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
	@printf '#!/usr/bin/env bash\n# llama-ai launcher -> runs %s with the %s venv.\nexec "%s" "%s/llama_ai.py" "$$@"\n' \
		"$(REPO)/llama_ai.py" "$(VENV)" "$(PY)" "$(REPO)" > "$(LAUNCHER)"
	@chmod +x "$(LAUNCHER)"
	@ln -sfn "$(REPO)/llama_ai.py" "$(BIN)/llama_ai.py"
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

uninstall: ## Remove the launcher + symlink (leaves the venv)
	@rm -f "$(LAUNCHER)" "$(BIN)/llama_ai.py"
	@echo "Removed $(LAUNCHER) and $(BIN)/llama_ai.py (venv kept at $(VENV); 'make -C tools clean' to drop requirements.txt)"

help:
	@echo "Targets: install (venv+launcher+symlink+smoke), venv-install, link, smoke,"
	@echo "         list, generate-requirements, version, uninstall, help"