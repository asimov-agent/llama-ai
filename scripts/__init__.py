"""Make scripts/ an importable package for the hermetic unit tests.

The launcher/download utilities live here (scripts/llama_serve.py,
scripts/hf_download.py) and the unit tests import scripts.llama_serve so the
tests exercise the relocated module rather than a stray top-level one.
"""
