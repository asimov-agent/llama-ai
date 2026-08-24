# GGUF model-tooling Makefile.
# Uses nerdctl (rootless) for the pip-compile container; installs deps into a
# python 3.10 venv at ~/llama-gguf-tools/.venv.

SHELL   := /bin/bash
NERDCTL ?= nerdctl
IMG     := gguf-tools/pip-compile:latest
PY310   ?= /opt/homebrew/bin/python3.10
VENV    := $(HOME)/llama-gguf-tools/.venv

REQIN   := requirements.in
REQTXT  := requirements.txt

.PHONY: all build-image generate-requirements generate-requirements-venv venv create-venv venv-install clean version

all: generate-requirements venv-install

# ---- flags -----------------------------------------------------------------
NERDCTL_TOOLS := $(shell command -v $(NERDCTL) >/dev/null 2>&1 && echo yes || echo no)

# ---- container ------------------------------------------------------------------
build-image: ## Build the pip-compile container (python 3.10)
	$(NERDCTL) build -t $(IMG) .

# ---- requirements ----------------------------------------------------------------
# Regenerate requirements.txt from requirements.in, so the locked, installable
# dependencies always stay in sync with the single source of truth (.in).
# Uses the pip-compile container when nerdctl is available, otherwise falls
# back to a venv pip-compile (pip-tools installed on demand).
generate-requirements: ## Compile requirements.in -> requirements.txt
	@if [ "$(NERDCTL_TOOLS)" = "yes" ]; then \
		echo "==> pip-compile via $(NERDCTL) container $(IMG)"; \
		$(MAKE) build-image; \
		$(NERDCTL) run --rm \
			-v "$(CURDIR)":/work:rw \
			-w /work \
			$(IMG); \
	else \
		echo "==> nerdctl not found; using venv pip-compile fallback"; \
		$(MAKE) generate-requirements-venv; \
	fi
	@echo "Regenerated $(REQTXT)"
	@echo "--- head of $(REQTXT) ---"
	@head -15 $(REQTXT)

generate-requirements-venv: venv-install ## pip-compile into the 3.10 venv (no container)
	$(VENV)/bin/python -m pip install --quiet pip-tools
	$(VENV)/bin/pip-compile --output-file $(REQTXT) $(REQIN)
	@echo "pip-compiled $(REQTXT) via venv"

# ---- venv ------------------------------------------------------------------------
create-venv: ## Create a python 3.10 virtualenv
	python3.10 -m venv $(VENV)
	@echo "venv at $(VENV)"

venv: create-venv ## alias

venv-install: create-venv $(REQTXT) ## Install generated requirements.txt into the 3.10 venv
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/pip install -r $(REQTXT)
	@echo "Installed gguf deps into $(VENV)"
	$(VENV)/bin/python -c "import gguf, numpy; print('gguf ok:', gguf.__file__)"

clean: ## Remove generated requirements.txt (keep .in as source of truth)
	rm -f $(REQTXT)

version: ## Show versions in the venv
	$(VENV)/bin/python -c "import gguf,numpy; print('numpy',numpy.__version__, 'gguf', gguf.__version__ if hasattr(gguf,'__version__') else 'n/a')"