#!/usr/bin/env python3
"""Download a GGUF into a tiered models folder with live progress + auto-resume/retry.

Usage: hf_download.py <repo_id> <filename> <dest_dir> <label> [refresh] [expected_bytes]
refresh: "1" -> ALWAYS consult the Hub (etag/hash) so a same-name file that was
updated upstream (or a corrupt local copy) is re-fetched, not skipped. Leave a
fully-fresh local file untouched (hf no-ops on matching etag).
Reads HF_TOKEN from ~/.zshrc. Append progress to <dest_dir>/<label>.progress.log
Uses HF_XET_HIGH_PERFORMANCE=1 (hf-xet chunked parallel) for speed — never
HF_HUB_DISABLE_XET (would force slow single-stream download).
Auto-retries on connection drop (rc!=0 while final .gguf absent), resuming the partial.
Stall-watch (issue #55): a still-alive download that makes NO forward progress for
HF_STALL_SECONDS (default 90) is terminated and retried, so a dead 0-MB/s connection
can never hang the sequential batch forever.
"""
import subprocess, sys, os, re, time, shutil

MAX_RETRY = 20
DEFAULT_STALL_SECONDS = 90


def _stall_decision(total, last_bytes, last_advancing, now):
    """Return (new_last_advancing, stalled_for).

    - If `total` grew since `last_bytes` (forward progress), reset the advancing
      marker to `now` and return stalled_for=0 (healthy).
    - Otherwise accumulate the no-growth window: stalled_for = now - last_advancing.

    A caller tests `stalled_for >= threshold` to decide a stall. This is the single
    stall-detection code path shared by the downloader loop and tests (issue #55).
    """
    if total > last_bytes:
        return now, 0.0
    return last_advancing, now - last_advancing


def tree_bytes(path, final_path):
    """Bytes of the CURRENT target file only (final + any live .incomplete partial).

    Counts just the file this downloader is fetching — NOT the whole model dir — so
    the percentage reflects only this model (resets to 0% for each new/next download)
    and isn't inflated by sibling models already in the same provider tier folder.
    """
    total = 0
    # the final file, if already fully placed
    if os.path.isfile(final_path):
        total += os.path.getsize(final_path)
    # the in-progress partial (hf writes `<etag>.incomplete` under .cache)
    cache_dir = os.path.join(path, ".cache")
    if os.path.isdir(cache_dir):
        for root, _, files in os.walk(cache_dir, topdown=True):
            for f in files:
                if f.endswith(".incomplete"):
                    p = os.path.join(root, f)
                    if os.path.isfile(p):
                        total += os.path.getsize(p)
    return total


def _resolve_expected_bytes(repo, filename, label, expected_bytes):
    """Total file size for a 0-100% progress readout, else None (best-effort)."""
    if expected_bytes and expected_bytes > 0:
        return expected_bytes
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


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    repo, filename, dest = argv[0], argv[1], argv[2]
    label = argv[3]
    refresh = (argv[4] if len(argv) > 4 else "0") == "1"
    expected_bytes = int(argv[5]) if len(argv) > 5 and str(argv[5]).isdigit() else None

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

    def write_log(msg):
        os.makedirs(dest, exist_ok=True)
        with open(log, "a") as lf:
            lf.write(msg + "\n")

    if tok:
        env["HF_TOKEN"] = tok
    # Speed: hf-xet (chunked parallel transfer) is ON by default in huggingface_hub.
    env["HF_XET_HIGH_PERFORMANCE"] = "1"
    env.pop("HF_HUB_ENABLE_HF_TRANSFER", None)
    env.pop("HF_HUB_DISABLE_XET", None)

    HF_BIN = os.environ.get("HF_BIN") or shutil.which("hf")
    if not HF_BIN or not os.path.isfile(HF_BIN):
        print(f"[{label}] ERROR: 'hf' CLI not found on PATH (no fallback).", file=sys.stderr)
        return 2
    cmd = [HF_BIN, "download", repo, filename,
           "--local-dir", dest, "--max-workers", "4"]
    final_path = os.path.join(dest, filename)

    TOTAL_BYTES = _resolve_expected_bytes(repo, filename, label, expected_bytes)
    stall_threshold = float(os.environ.get("HF_STALL_SECONDS", str(DEFAULT_STALL_SECONDS)))

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
        last_advancing = time.time()  # last time the tree actually grew (stall-watch)
        stalled_for = 0.0
        while proc.poll() is None:
            total = tree_bytes(dest, final_path)
            now = time.time()
            # stall watch (issue #55): if no forward progress for >= threshold while the
            # subprocess is STILL ALIVE, terminate it so the retry loop advances instead
            # of hanging forever on a dead 0-MB/s connection.
            last_advancing, stalled_for = _stall_decision(total, last_bytes, last_advancing, now)
            if stalled_for >= stall_threshold:
                line = (f"[{time.strftime('%H:%M:%S')}] STALLED → no progress for "
                        f"{stalled_for:.0f}s; terminating & retrying attempt {attempt + 1}")
                write_log(line)
                print(line, flush=True)
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                break  # fall out to the retry logic; attempt increments below
            if now - last_log >= 5:
                dt = now - t0
                mbps = total / dt / 1e6 if dt > 0 else 0
                if TOTAL_BYTES:
                    pct = min(100.0, total / TOTAL_BYTES * 100)
                    line = (f"[{time.strftime('%H:%M:%S')}] {pct:5.1f}% "
                            f"({total/1e9:6.2f}/{TOTAL_BYTES/1e9:.2f} GB) | "
                            f"{mbps:.1f} MB/s | attempt {attempt} | running {dt/60:.1f} min")
                    write_log(line)
                    print(line, flush=True)
                else:
                    line = (f"[{time.strftime('%H:%M:%S')}] {total/1e9:6.2f} GB so far | "
                            f"{mbps:.1f} MB/s | attempt {attempt} | running {dt/60:.1f} min")
                    write_log(line)
                    print(line, flush=True)
                last_log = now
            last_bytes = total
            time.sleep(3)
        # process ended
        try:
            out = proc.stdout.read() if proc.stdout else ""
            if out:
                write_log("\n--- cli tail ---\n" + out[-800:] + "\n")
        except Exception:
            pass
        rc = proc.wait()
        write_log(f"--- attempt {attempt} ended rc={rc} {time.ctime()}, "
                  f"disk={tree_bytes(dest, final_path)/1e9:.2f} GB ---")
        if rc == 0 and os.path.exists(final_path):
            write_log(f"\nDONE {time.ctime()} (attempt {attempt}, total {attempt} runs) final_file={final_path}")
            print(f"[{label}] COMPLETE rc=0 attempt={attempt} final_file={final_path}", flush=True)
            break
        # rc != 0 => connection likely dropped OR we stall-terminated; retry (resumes partial)
        write_log(f"--- rc={rc}; retrying to resume partial ---")
        attempt += 1
        time.sleep(5)
    else:
        write_log(f"\nFAILED after {MAX_RETRY} attempts {time.ctime()} disk={tree_bytes(dest, final_path)/1e9:.2f} GB")
        print(f"[{label}] FAILED after {MAX_RETRY} attempts; disk={tree_bytes(dest, final_path)/1e9:.2f} GB log={log}", flush=True)
        return 1

    print(f"[{label}] done final={tree_bytes(dest, final_path)/1e9:.2f} GB log={log}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())