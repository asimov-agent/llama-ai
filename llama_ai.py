def build_command(meta, ctx, port):
    global LLAMA_SERVER
    cmd = [LLAMA_SERVER,
           "-m", meta["file"],
           "--host", "0.0.0.0",
           "--port", str(port),
           "-c", str(ctx),
           "-ngl", "99",            # offload every layer to Metal
           "-fa", "on",             # flash attention
           "--jinja",               # use model chat template
           "-ctk", KV_QUANT, "-ctv", KV_QUANT,
           "-b", "2048", "-ub", "512",
           "--cont-batching",
           "--metrics"]
    # Sampling flags: use the model's author-recommended defaults (general.sampling.*)
    # when present, otherwise fall back to the global preset. Empty meta["sampling"]
    # => emit only the preset so metadata-free models keep their old behaviour.
    sampling = meta.get("sampling") or {}
    if sampling:
        cmd += [f"{SAMPLING_FLAG_MAP[k]} {v}" for k, v in sampling.items()]
    else:
        cmd += list(SAMPLING)
    # reasoning-capable model: enable reasoning + return thoughts in
    # `message.reasoning_content` (deepseek format) so thinking is preserved.
    if is_reasoning_model(meta):
        cmd += ["--reasoning", "on", "--reasoning-format", "deepseek"]
    # parallel slots: 2 for small models, 1 for big
    np_slots = 2 if meta["size_gb"] < 10 else 1
    cmd += ["-np", str(np_slots)]
    # FIXED alias so the serving endpoint keeps the SAME name across model
    # switches. Clients (Hermes server, agent CLIs) pin one name and keep
    # working no matter which model is loaded. The real model id is still
    # served under the per-model filename alias as well.
    STABLE_ALIAS = "llm-local"
    cmd += ["--alias", STABLE_ALIAS]
    return cmd
