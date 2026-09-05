#!/usr/bin/env python3
"""Download a GGUF into a tiered models folder with live progress + auto-resume/retry.

Usage: hf_download.py <repo_id> <filename> <dest_dir> <label> [refresh]
refresh: "1" -> ALWAYS consult the Hub (etag/hash) so a same-name file that was
updated upstream (or a corrupt local copy) is re-fetched, not skipped. Leave a
fully-fresh local file untouched (hf no-ops on matching etag).
Reads HF_TOKEN from ~/.zshrc. Append progress to <dest_dir>/<label>.progress.log
Uses HF_XET_HIGH_PERFORMANCE=1 (hf-xet chunked parallel) for speed — never
HF_HUB_DISABLE_XET (would force slow single-stream download).
Auto-retries on connection drop (rc!=0 while final .gguf absent), resuming the partial.
"""
import subprocess, sys, os, re, time, shutil

repo, filename, dest, label = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
refresh = (sys.argv[5] if len(sys.argv) > 5 else "0") == "1"
# Optional expected total bytes (for a 0-100% progress readout). If absent we query
# the HF API for the file size.
expected_bytes = int(sys.argv[6]) if len(sys.argv) > 6 and str(sys.argv[6]).isdigit() else None

tok = None
try:
    content = open(os.path.expanduser("~/.zshrc")).read()
    m = re.search(r"HF_TOKEN=(hf_[A-Za-z0-9]+)", content)
    tok = m.group(1) if m else None
except Exception:
    pass

os.makedirs(dest, exist_ok=True)
log = os.path.join(dest, f"{label}.progress.log")
env = dict(os.environ)
if tok:
    env["HF_TOKEN"] = tok
# Speed: hf-xet (chunked parallel transfer) is ON by default in huggingface_hub.
# Enable its HIGH-PERFORMANCE mode (the modern flag; HF_HUB_ENABLE_HF_TRANSFER is
# deprecated and no longer used), and never set HF_HUB_DISABLE_XET=1 (that forced
# the slow single-stream path). A single large .gguf then downloads across many
# parallel connections.
env["HF_XET_HIGH_PERFORMANCE"] = "1"
env.pop("HF_HUB_ENABLE_HF_TRANSFER", None)
env.pop("HF_HUB_DISABLE_XET", None)

HF_BIN = os.environ.get("HF_BIN") or shutil.which("hf")
if not HF_BIN or not os.path.isfile(HF_BIN):
    print(f"[{label}] ERROR: 'hf' CLI not found on PATH (no fallback).", file=sys.stderr)
    sys.exit(2)
cmd = [HF_BIN, "download", repo, filename,
       "--local-dir", dest, "--max-workers", "4"]
final_path = os.path.join(dest, filename)
MAX_RETRY = 20

def tree_bytes(path):
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            if f.endswith(".lock") or "progress.log" in f:
                continue
            total += os.path.getsize(os.path.join(root, f))
    return total

# ---------------------------------------------------------------------------
# Resolve the total size so progress can report 0-100%.
# ---------------------------------------------------------------------------
def resolve_expected_bytes():
    if expected_bytes and expected_bytes > 0:
        return expected_bytes
    # Query the HF model tree API for this file's size.
    import json
    import urllib.request
    try:
        url = f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true"
        req = urllib.request.Request(url, headers={"User-Agent": f"llama-ai/{label}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        for f in data:
            if f.get("path", "").endswith(filename) and f.get("size"):
                return int(f["size"])
    except Exception:
        pass
    return None


TOTAL_BYTES = resolve_expected_bytes()


def write_log(msg):
    os.makedirs(dest, exist_ok=True)   # ensure the log dir exists (e.g. after interruption)
    with open(log, "a") as lf:
        lf.write(msg + "\n")

write_log(f"MODE download {repo} :: {filename} -> {dest}\nSTART {time.ctime()} | max_retry={MAX_RETRY}\n")

t_total = time.time()
attempt = 1
while attempt <= MAX_RETRY:
    # WITHOUT refresh: a fully-present file is treated as done (fast path).
    # WITH refresh: always run `hf download` — it etag/checks the Hub and no-ops
    # fast if the local file's content hash still matches; if the file was
    # UPDATED upstream (even same filename + same size), the etag differs and hf
    # re-fetches just that file. A mere existence check would mask that update.
    if (not refresh) and os.path.exists(final_path):
        break  # already done
    write_log(f"\n=== attempt {attempt} ({time.ctime()}) {('refresh' if refresh else 'plain')} ===")
    t0 = time.time()
    proc = subprocess.Popen(cmd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    last_bytes = -1
    last_log = 0.0
    while proc.poll() is None:
        total = tree_bytes(dest)
        now = time.time()
        if now - last_log >= 5:
            dt = now - t0
            mbps = total / dt / 1e6 if dt > 0 else 0
            if TOTAL_BYTES:
                pct = min(100.0, total / TOTAL_BYTES * 100)
                write_log(f"[{time.strftime('%H:%M:%S')}] {pct:5.1f}% "
                          f"({total/1e9:6.2f}/{TOTAL_BYTES/1e9:.2f} GB) | "
                          f"{mbps:.1f} MB/s | attempt {attempt} | running {dt/60:.1f} min")
            else:
                write_log(f"[{time.strftime('%H:%M:%S')}] {total/1e9:6.2f} GB so far | "
                          f"{mbps:.1f} MB/s | attempt {attempt} | running {dt/60:.1f} min")
            # stall watch (no growth ~60s)
            if total == last_bytes:
                pass  # will accumulate stall detection below
            last_log = now
        last_bytes = total
        time.sleep(3)
    # process ended
    try:
        out = proc.stdout.read()
        if out:
            write_log("\n--- cli tail ---\n" + out[-800:] + "\n")
    except Exception:
        pass
    rc = proc.wait()
    write_log(f"--- attempt {attempt} ended rc={rc} {time.ctime()}, "
              f"disk={tree_bytes(dest)/1e9:.2f} GB ---")
    if rc == 0 and os.path.exists(final_path):
        write_log(f"\nDONE {time.ctime()} (attempt {attempt}, total {attempt} runs) final_file={final_path}")
        print(f"[{label}] COMPLETE rc=0 attempt={attempt} final_file={final_path}", flush=True)
        break
    # rc != 0 => connection likely dropped; retry (resumes partial)
    write_log(f"--- rc={rc}; retrying to resume partial ---")
    attempt += 1
    time.sleep(5)
else:
    write_log(f"\nFAILED after {MAX_RETRY} attempts {time.ctime()} disk={tree_bytes(dest)/1e9:.2f} GB")
    print(f"[{label}] FAILED after {MAX_RETRY} attempts; disk={tree_bytes(dest)/1e9:.2f} GB log={log}", flush=True)
    sys.exit(1)

print(f"[{label}] done final={tree_bytes(dest)/1e9:.2f} GB log={log}", flush=True)
