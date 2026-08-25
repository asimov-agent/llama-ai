#!/usr/bin/env python3
"""Download a GGUF into a tiered models folder with live progress + auto-resume/retry.

Usage: hf_download.py <repo_id> <filename> <dest_dir> <label>
Reads HF_TOKEN from ~/.zshrc. Append progress to <dest_dir>/<label>.progress.log
Uses HF_HUB_ENABLE_HF_TRANSFER=1 + HF_HUB_DISABLE_XET=1 for speed.
Auto-retries on connection drop (rc!=0 while final .gguf absent), resuming the partial.
"""
import subprocess, sys, os, re, time, shutil

repo, filename, dest, label = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

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
env["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
env["HF_HUB_DISABLE_XET"] = "1"

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

def write_log(msg):
    with open(log, "a") as lf:
        lf.write(msg + "\n")

write_log(f"MODE download {repo} :: {filename} -> {dest}\nSTART {time.ctime()} | max_retry={MAX_RETRY}\n")

t_total = time.time()
attempt = 1
while attempt <= MAX_RETRY:
    if os.path.exists(final_path):
        break  # already done
    write_log(f"\n=== attempt {attempt} ({time.ctime()}) ===")
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
            write_log(f"[{time.strftime('%H:%M:%S')}] {total/1e9:.2f} GB so far | "
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
