# GGUF tooling: pip-compile resolver container (matches repo pattern).
# Build with nerdctl, run to compile requirements.in -> requirements.txt.
FROM python:3.10-slim

RUN pip install --no-cache-dir pip-tools

WORKDIR /work

# The requirements.in is bind-mounted at /work by the Makefile; this container
# only pins CONTAINER-side tooling (pip-tools). Runtime deps are compiled by
# pip-compile against the mounted .in file.
CMD ["pip-compile", "requirements.in", "-o", "requirements.txt"]
