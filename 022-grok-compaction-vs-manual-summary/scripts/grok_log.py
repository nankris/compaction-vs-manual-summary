#!/usr/bin/env python3
"""grok_log.py - run one headless Grok Build CLI call and append its exact usage/cost to a CSV.

Usage (CLI):  grok_log.py --csv log.csv --label summarise --prompt "..." [--cwd DIR] [--rep 1] [--extra "--always-approve"]
As module:    from grok_log import run_grok; row = run_grok(prompt, label, csv_path, cwd=..., extra=[...])

Stops early (raises QuotaHit) if a STOP file exists or Grok returns a usage/rate-limit error.
"""
import argparse, csv, json, os, subprocess, sys, time, datetime, re, shlex

FIELDS = ["ts_ist", "experiment", "label", "rep", "model", "input_tokens", "cache_read_input_tokens",
          "cache_creation_input_tokens", "total_input_tokens", "cached_share", "output_tokens", "reasoning_tokens",
          "total_tokens", "cost_usd", "cost_usd_ticks", "latency_s", "num_turns", "exit_code",
          "stop_reason", "limit_hit", "error"]
STOP_FILE = os.environ.get("GROK_STOP_FILE", "/workspace/work/tig/_shared/QUOTA_STOP")
LIMIT_RE = re.compile(r"(rate.?limit|usage.?limit|quota|too many requests|\b429\b|limit reached|exceeded)", re.I)

class QuotaHit(Exception):
    pass

def ist_now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M:%S")

def run_grok(prompt, label, csv_path, experiment="", rep=1, cwd=None, extra=None, timeout=900):
    if os.path.exists(STOP_FILE):
        raise QuotaHit(open(STOP_FILE).read())
    cmd = ["grok", "--no-auto-update", "-p", prompt, "--output-format", "json"] + (extra or [])
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        out, err, code = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out, err, code = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "TIMEOUT", -9
    lat = time.time() - t0
    data = {}
    try:
        data = json.loads(out[out.index("{"):]) if "{" in out else {}
    except Exception:
        pass
    u = data.get("usage", {}) or {}
    mu = data.get("modelUsage", {}) or {}
    model = ",".join(mu.keys())
    # NOTE: Grok CLI reports input_tokens EXCLUDING cache reads (Anthropic-style); total input = input + cache_read
    inp = u.get("input_tokens", 0) or 0
    cr = u.get("cache_read_input_tokens", 0) or 0
    text = data.get("text", "") or ""
    errtxt = "" if (code == 0 and data) else (err.strip() + " " + out.strip())[:500]
    limit = bool(errtxt and LIMIT_RE.search(errtxt))
    row = dict(ts_ist=ist_now(), experiment=experiment, label=label, rep=rep, model=model,
               input_tokens=inp, cache_read_input_tokens=cr,
               cache_creation_input_tokens=u.get("cache_creation_input_tokens", 0),
               total_input_tokens=inp + cr, cached_share=round(cr / (inp + cr), 4) if (inp + cr) else "", output_tokens=u.get("output_tokens", 0),
               reasoning_tokens=u.get("reasoning_tokens", 0), total_tokens=u.get("total_tokens", 0),
               cost_usd=data.get("total_cost_usd", ""), cost_usd_ticks=data.get("total_cost_usd_ticks", ""),
               latency_s=round(lat, 2), num_turns=data.get("num_turns", ""), exit_code=code,
               stop_reason=data.get("stopReason", ""), limit_hit=int(limit), error=errtxt.replace("\n", " "))
    new = not os.path.exists(csv_path)
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new: w.writeheader()
        w.writerow(row)
    row["text"] = text
    row["raw"] = data
    if limit:
        with open(STOP_FILE, "w") as f:
            f.write(f"{ist_now()} {label}: {errtxt[:300]}")
        raise QuotaHit(errtxt)
    return row

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True); ap.add_argument("--label", required=True)
    ap.add_argument("--prompt", required=True); ap.add_argument("--cwd"); ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--experiment", default=""); ap.add_argument("--extra", default="")
    a = ap.parse_args()
    try:
        r = run_grok(a.prompt, a.label, a.csv, a.experiment, a.rep, a.cwd, shlex.split(a.extra))
        print(r["text"]); print(f"[cost ${r['cost_usd']} in={r['input_tokens']} cached={r['cache_read_input_tokens']} out={r['output_tokens']} {r['latency_s']}s]", file=sys.stderr)
    except QuotaHit as e:
        print("QUOTA/RATE LIMIT HIT:", e, file=sys.stderr); sys.exit(3)
