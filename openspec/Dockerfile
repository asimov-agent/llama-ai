# OpenSpec CLI container for llama-ai.
#
# Runs the official @fission-ai/openspec CLI inside a Node image. The repo is
# bind-mounted at /repo (working dir), so `openspec new change <name>` and
# `openspec validate <name>` operate on the repository's own openspec/ tree.
#
# Build the image with the Makefile target, not by hand:
#     make openspec-image
#
# Then use the Makefile targets to drive the CLI:
#     make openspec-new NAME=<change>           # openspec new change <change>
#     make openspec-validate NAME=<change>      # openspec validate <change>
#     make openspec-status                      # openspec status
#     make openspec-shell                       # interactive shell into the repo
#
# Mount layout inside the container:
#     /repo        -> repository root (bind mount, rw): contains openspec/ + repo files
#     /repo/node_modules  -> not persisted in git (volume); openspec lives in /usr/local/lib/node_modules
FROM node:22-alpine

# openspec CLI (pinned; @fission-ai/openspec)
ARG OPENSPEC_VERSION=1.10.0
RUN npm install -g @fission-ai/openspec@${OPENSPEC_VERSION} \
    && openspec --version

WORKDIR /repo

# The repo is mounted at /repo by the Makefile (docker run -v "$(REPO):/repo").
# Default command: drop into the CLI's help.
CMD ["openspec", "--help"]
