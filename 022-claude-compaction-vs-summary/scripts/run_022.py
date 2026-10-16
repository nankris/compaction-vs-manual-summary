#!/usr/bin/env python3
"""#022 Claude arm: plant 15 facts over 15 resumed turns (with filler), then compare
full (keep going) / compact (/compact headless) / manual (handoff note -> fresh session).
After the branch point: 3 filler turns, then a from-memory quiz. Every call's JSON is saved raw.
Usage: run_022.py ARM REP
"""
import json, os, random, subprocess, sys, time
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(D, "work")
FLAGS = ["--output-format", "json", "--model", "sonnet", "--tools", "", "--strict-mcp-config"]
FACTS = [  # (planted sentence, quiz question, gold regex)
    ("The staging database listens on port 6543.", "What port does the staging database listen on?", r"6543"),
    ("The on-call engineer for the payments service is Priya Ramanathan.", "Who is on-call for payments?", r"priya"),
    ("Our release codename for Q4 is BLUE HERON.", "What is the Q4 release codename?", r"blue\s*heron"),
    ("The feature flag that gates the new checkout is ff_checkout_v7.", "Which feature flag gates the new checkout?", r"ff_checkout_v7"),
    ("The S3 bucket for nightly backups is acme-bkp-ap-south-1-0419.", "Name the nightly backup S3 bucket.", r"acme-bkp-ap-south-1-0419"),
    ("We pinned Node to version 20.11.1 because 20.12 broke our build.", "Which Node version is pinned?", r"20\.11\.1"),
    ("The max retry count for the webhook sender is 7.", "What is the webhook sender's max retry count?", r"\b7\b|seven"),
    ("The incident from 3 March was caused by an expired TLS cert on api-gw-2.", "What caused the 3 March incident (and on which host)?", r"(?=.*(tls|cert))(?=.*api-gw-2)"),
    ("Customer Zentrix Ltd has a custom rate limit of 1800 requests per minute.", "What custom rate limit does Zentrix Ltd have?", r"1[,.]?800"),
    ("The cron job reindex-search runs at 02:15 UTC.", "When does reindex-search run?", r"02:15|2:15"),
    ("Our Grafana dashboard ID for latency is 88213.", "What is the Grafana latency dashboard ID?", r"88213"),
    ("The legacy endpoint /v1/orders/export will be removed on 2026-11-30.", "When will /v1/orders/export be removed?", r"2026-11-30|30 nov|nov(ember)? 30"),
    ("The JWT signing key rotates every 45 days.", "How often does the JWT signing key rotate?", r"\b45\b"),
    ("The default page size for the search API is 37.", "What is the search API's default page size?", r"\b37\b"),
    ("The warehouse in Pune has the internal site code PNQ-W3.", "What is the Pune warehouse's site code?", r"pnq-w3"),
]
WORDS = ("service request latency queue worker deploy config rollout metric alert cache shard replica "
         "token header payload batch schema migration index backlog ticket review merge branch pipeline").split()

def filler(seed, n=500):
    r = random.Random(str(seed))
    sents = []
    while sum(len(s.split()) for s in sents) < n:
        sents.append(" ".join(r.choice(WORDS) for _ in range(r.randint(8, 16))).capitalize() + ".")
    return " ".join(sents)

def call(prompt, log, label, resume=None, cwd=WORK):
    cmd = ["claude", "-p", prompt] + FLAGS + (["--resume", resume] if resume else [])
    t0 = time.time(); p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
    try: d = json.loads(p.stdout)
    except Exception: d = {"error": p.stdout[-500:] + p.stderr[-500:]}
    u = d.get("usage", {}) or {}
    row = dict(label=label, wall=round(time.time() - t0, 1), cost=d.get("total_cost_usd", 0), session=d.get("session_id"),
               inp=u.get("input_tokens", 0), cw=u.get("cache_creation_input_tokens", 0), cr=u.get("cache_read_input_tokens", 0),
               out=u.get("output_tokens", 0), text=d.get("result", ""), raw=d)
    row["ctx"] = row["inp"] + row["cw"] + row["cr"]
    log.append(row); print(label, row["cost"], row["ctx"], flush=True)
    return row

def main(arm, rep):
    log = []; path = f"{D}/results/raw/session_{arm}_r{rep}.json"
    intro = "We are doing a long project-notes session. Each turn I paste a status log with one key fact. Reply in at most 2 sentences."
    sid = None
    for i, (fact, _, _) in enumerate(FACTS):
        msg = (intro + "\n\n" if i == 0 else "") + f"Status log #{i+1}:\n{filler((rep, i))}\nKEY FACT: {fact}\n{filler((rep, i, 'b'), 250)}\nAcknowledge briefly."
        sid = call(msg, log, f"plant{i+1}", sid)["session"]
    if arm == "compact":
        call("/compact", log, "compact", sid)
    elif arm == "manual":
        note = call("Write a compact handoff note for a fresh assistant who will continue this session without seeing it. "
                    "Keep every concrete fact (numbers, names, IDs, dates) verbatim; drop the filler. Output only the note.", log, "handoff", sid)["text"]
        sid = call("Handoff note from a previous session:\n\n" + note + "\n\nWe continue the project-notes session. Reply in at most 2 sentences. Acknowledge.", log, "fresh_seed")["session"]
    for j in range(3):
        sid = call(f"Status log #{16+j} (no key fact):\n{filler((rep, 'post', j))}\nAcknowledge briefly.", log, f"post{j+1}", sid)["session"]
    qs = "\n".join(f"Q{k+1}: {q}" for k, (_, q, _) in enumerate(FACTS))
    call("From memory of this session only, answer each question on its own line as 'Qn: answer'. Say 'unknown' if you don't know.\n" + qs, log, "quiz", sid)
    json.dump(dict(arm=arm, rep=rep, calls=log), open(path, "w"), indent=1)

if __name__ == "__main__":
    os.makedirs(WORK, exist_ok=True); main(sys.argv[1], int(sys.argv[2]))
