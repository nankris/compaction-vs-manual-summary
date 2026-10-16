# #022 Grok compaction vs manual summaries on a 12-turn resumed codebase audit (public repo pallets/itsdangerous).
# Arms (ARM env or all): full = 12 resumed turns, no compaction
#                        compact = turns 1-6, then built-in `/compact`, then turns 7-12 resumed
#                        manual = turns 1-6, then Grok writes a handoff note; turns 7-12 in a FRESH session seeded with the note
#                        auto = 12 resumed turns with the auto-compact threshold lowered in ~/.grok/config.toml (run separately)
import json, os, sys, shutil, tempfile, time, glob, concurrent.futures as cf
sys.path.insert(0, os.path.dirname(__file__))
from grok_log import run_grok, QuotaHit
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = f"{D}/fixture/itsdangerous"
CSV = f"{D}/results/grok_calls.csv"
LEAN = ["--system-prompt-override", "You are a careful code auditor working in a local repository. Use the read_file tool to read files. Be brief.",
        "--disable-web-search", "--no-subagents", "--tools", "read_file"]
NOTOOLS = LEAN + ["--disallowed-tools", "read_file"]
FMT = " Answer only with lines of the form 'F<n>: <answer>'."
TURNS = [
    "We are auditing the itsdangerous library in this folder over many turns; I will quiz you on your findings at the end, so remember them. "
    "Read src/itsdangerous/signer.py. F1: the default salt of Signer? F2: the default key_derivation? F3: all key_derivation values derive_key accepts?",
    "Read src/itsdangerous/serializer.py. F4: the default salt of Serializer? F5: the module used as default_serializer?",
    "Read src/itsdangerous/timed.py. F6: the exception raised when a signature is older than max_age? F7: the timezone of the datetime returned by timestamp_to_datetime?",
    "Read src/itsdangerous/url_safe.py. F8: the byte prefix that marks a compressed payload? F9: the compression module used?",
    "Read src/itsdangerous/exc.py. F10: the base class of all itsdangerous exceptions? F11: the direct parent class of SignatureExpired?",
    "Read CHANGES.rst and pyproject.toml. F12: the requires-python value? F13: the release date of version 2.2.0?",
    "Read tests/test_itsdangerous/test_signer.py. F14: the separator value test_invalid_separator passes? F15: how many functions named test_* the file defines?",
    "Read tests/test_itsdangerous/test_serializer.py. F16: how many functions named test_* the file defines? F17: the name of the test for fallback signers?",
    "Read tests/test_itsdangerous/test_timed.py. F18: the library used to freeze time? F19: the exception attribute test_timestamp_missing asserts is None?",
    "Read docs/concepts.rst. F20: the stronger digest method the docs suggest instead of SHA-1? F21: in the key rotation example, after how many weeks is a key rotated out?",
    "Without reading any more files, write a short Python snippet (max 12 lines) that makes a URLSafeTimedSerializer with salt 'reset', "
    "dumps {'id': 5}, then loads it with a max age of one hour, and handles the expired case and the bad-signature case with the right exception classes "
    "imported from itsdangerous. Reply with the code only.",
    "Final quiz, from memory only (do not use tools). Give your answer for every finding F1 to F21 in order, one line each as 'F<n>: <answer>'. "
    "If unsure, give your best guess.",
]
# v2 "hard" task: 14 reading turns, 42 detail facts (line numbers, exact messages, versions), compaction point after turn 8, quiz at turn 15
TURNS2 = [
    "We are auditing the itsdangerous library in this folder over many turns; at the end I will quiz you on every finding from memory, so keep them. "
    "Read src/itsdangerous/signer.py. H1: the line number where `class Signer:` is defined? H2: the name of the helper that turns the secret_key argument into a list? H3: the exact message of the TypeError for an unknown key derivation?",
    "Read src/itsdangerous/serializer.py. H4: the line number of the `class Serializer` definition? H5: the name of the module-level function that checks whether a serializer is text-based? H6: the default salt of Serializer?",
    "Read src/itsdangerous/timed.py. H7: the line number of the `class TimedSerializer` definition? H8: the exact message of the BadTimeSignature raised when the timestamp is missing? H9: the exact f-string message of SignatureExpired when age > max_age?",
    "Read src/itsdangerous/url_safe.py. H10: the line number of the `class URLSafeTimedSerializer` definition? H11: the compression module used? H12: the name of the mixin class?",
    "Read src/itsdangerous/exc.py. H13: the line number of the `class BadHeader` definition? H14: the parent class of BadPayload? H15: the parent class of BadHeader?",
    "Read src/itsdangerous/encoding.py. H16: the exact message of the BadData raised for invalid base64? H17: the name of the function that converts an int to bytes? H18: the line number of `def base64_decode`?",
    "Read src/itsdangerous/_json.py and src/itsdangerous/__init__.py. H19: the class name defined in _json.py? H20: the default separators it passes to json.dumps? H21: how many names __init__.py re-exports?",
    "Read CHANGES.rst. H22: the release date of 2.1.2? H23: the release date of 2.0.0? H24: the release date of 2.1.0?",
    "Read pyproject.toml. H25: the build-backend? H26: the python_version set for mypy? H27: the pytest testpaths?",
    "Read uv.lock. H28: the locked version of freezegun? H29: the locked version of pytest? H30: how many [[package]] entries the file has?",
    "Read tests/test_itsdangerous/test_signer.py. H31: the separator passed in test_invalid_separator? H32: how many functions named test_* it defines? H33: the line number of `def test_secret_keys`?",
    "Read tests/test_itsdangerous/test_serializer.py. H34: how many functions named test_* it defines? H35: the line number of `def test_digests`? H36: the name of the fallback-signers test?",
    "Read tests/test_itsdangerous/test_timed.py. H37: the library used to freeze time? H38: the exception attribute test_timestamp_missing asserts is None? H39: the line number of `class TestTimedSerializer`?",
    "Read docs/concepts.rst. H40: the stronger digest the docs suggest instead of SHA-1? H41: in the key rotation example, after how many weeks is a key rotated out? H42: how many weeks it takes the attacker to crack a key in that example?",
    "Final quiz, from memory only (do not use tools). Give your answer for every finding H1 to H42 in order, one line each as 'H<n>: <answer>'. If unsure, give your best guess.",
]
HANDOFF2 = ("Write a handoff note so a brand-new session with no memory of this conversation can continue this audit and pass the final quiz. "
            "Include the task context and every finding so far (H1-H24) with its exact value. Be compact. Reply with the note only.")
HANDOFF = ("Write a handoff note so a brand-new session with no memory of this conversation can continue this audit and pass the final quiz. "
           "Include the task context and every finding so far (F1-F13) with its exact value. Be compact. Reply with the note only.")

def updates_events(cwd, sid):
    out = []
    for f in glob.glob(os.path.expanduser(f"~/.grok/sessions/*/{sid}/updates.jsonl")):
        for line in open(f):
            if "compact" in line:
                try:
                    u = json.loads(line)["params"]["update"]
                    if u.get("sessionUpdate", "").startswith("auto_compact") or u.get("sessionUpdate") == "compaction_checkpoint":
                        out.append({k: v for k, v in u.items() if k in ("sessionUpdate", "tokens_before", "tokens_after", "checkpoint_id")})
                except Exception:
                    pass
    return out

def call(prompt, label, sid, cwd, extra, tries=2):
    for t in range(tries):
        ex = list(extra) + (["-r", sid] if sid else [])
        r = run_grok(prompt, label, CSV, "022", 1, cwd=cwd, extra=ex)
        if r["exit_code"] == 0 and (r["text"] or prompt.startswith("/")):
            return r
        time.sleep(3)
    return r

TASK = os.environ.get("TASK", "v1")
def run_arm(arm, rep):
    if TASK == "v2":
        return run_arm2(arm, rep)
    out = f"{D}/results/session_{arm}_r{rep}.json"
    if os.path.exists(out):
        return json.load(open(out))
    cwd = tempfile.mkdtemp(prefix=f"g022_{arm}_r{rep}_"); shutil.copytree(FIX, cwd, dirs_exist_ok=True)
    rec = dict(arm=arm, rep=rep, cwd=cwd, turns=[], sessions=[])
    sid = None
    def turn(i, prompt, label, extra=LEAN):
        nonlocal sid
        r = call(prompt, label, sid, cwd, extra)
        sid = sid or r["raw"].get("sessionId")
        rec["turns"].append(dict(turn=i, label=label, session=sid, text=r["text"], input=r["input_tokens"], cached=r["cache_read_input_tokens"],
                                 total_in=r["total_input_tokens"], out=r["output_tokens"], reasoning=r["reasoning_tokens"],
                                 cost=r["cost_usd"], latency=r["latency_s"], exit=r["exit_code"], ok=int(r["exit_code"] == 0 and bool(r["text"]))))
        json.dump(rec, open(out + ".part", "w"), indent=1)
    lab = lambda i: f"{arm}_r{rep}_t{i:02d}"
    for i in range(6):
        turn(i + 1, TURNS[i] + FMT, lab(i + 1))
    if arm == "compact":
        r = call("/compact", lab(6) + "_compact", sid, cwd, LEAN)
        rec["compaction_call"] = dict(exit=r["exit_code"], latency=r["latency_s"], cost=r["cost_usd"])
    if arm == "manual":
        turn(6.5, HANDOFF, lab(6) + "_handoff")
        note = rec["turns"][-1]["text"]; rec["handoff_note"] = note; rec["sessions"].append(sid); sid = None
        first7 = ("Context from a previous session of this same task:\n<<<\n" + note + "\n>>>\n\n") + TURNS[6] + FMT
    for i in range(6, 12):
        p = TURNS[i] + (FMT if i < 10 else "")
        if arm == "manual" and i == 6:
            p = first7
        turn(i + 1, p, lab(i + 1), NOTOOLS if i == 11 else LEAN)
    rec["sessions"].append(sid)
    rec["compaction_events"] = {s: updates_events(cwd, s) for s in rec["sessions"] if s}
    json.dump(rec, open(out, "w"), indent=1); os.remove(out + ".part")
    shutil.rmtree(cwd, ignore_errors=True)
    return rec

def run_arm2(arm, rep):
    out = f"{D}/results/session_v2_{arm}_r{rep}.json"
    if os.path.exists(out):
        return json.load(open(out))
    # resumable: persistent cwd + .part record (the sandbox can restart mid-run)
    cwd = f"{D}/work_tmp/v2_{arm}_r{rep}"
    if os.path.exists(out + ".part") and os.path.isdir(cwd):
        rec = json.load(open(out + ".part")); sid = rec["turns"][-1]["session"] if rec["turns"] else None
        if arm == "manual" and rec.get("handoff_note") and rec["turns"][-1]["turn"] == 8.5: sid = None
    else:
        shutil.rmtree(cwd, ignore_errors=True); shutil.copytree(FIX, cwd)
        rec = dict(task="v2", arm=arm, rep=rep, cwd=cwd, turns=[], sessions=[]); sid = None
    done = {t["label"] for t in rec["turns"]}
    F2 = " Answer only with lines of the form 'H<n>: <answer>'."
    def turn(i, prompt, label, extra=LEAN):
        nonlocal sid
        if label in done: return
        r = call(prompt, label, sid, cwd, extra)
        sid = sid or r["raw"].get("sessionId")
        rec["turns"].append(dict(turn=i, label=label, session=sid, text=r["text"], input=r["input_tokens"], cached=r["cache_read_input_tokens"],
                                 total_in=r["total_input_tokens"], out=r["output_tokens"], reasoning=r["reasoning_tokens"],
                                 cost=r["cost_usd"], latency=r["latency_s"], exit=r["exit_code"], ok=int(r["exit_code"] == 0 and bool(r["text"]))))
        json.dump(rec, open(out + ".part", "w"), indent=1)
    lab = lambda i: f"v2_{arm}_r{rep}_t{i:02d}"
    for i in range(8):
        turn(i + 1, TURNS2[i] + F2, lab(i + 1))
    first9 = TURNS2[8] + F2
    if arm == "compact" and "compaction_call" not in rec:
        r = call("/compact", lab(8) + "_compact", sid, cwd, LEAN)
        rec["compaction_call"] = dict(exit=r["exit_code"], latency=r["latency_s"], cost=r["cost_usd"])
        json.dump(rec, open(out + ".part", "w"), indent=1)
    if arm == "manual":
        if "handoff_note" not in rec:
            turn(8.5, HANDOFF2, lab(8) + "_handoff")
            rec["handoff_note"] = rec["turns"][-1]["text"]; rec["sessions"].append(sid); sid = None
            json.dump(rec, open(out + ".part", "w"), indent=1)
        note = rec["handoff_note"]
        first9 = "Context from a previous session of this same task:\n<<<\n" + note + "\n>>>\n\n" + first9
    for i in range(8, 15):
        p = first9 if i == 8 else (TURNS2[i] + (F2 if i < 14 else ""))
        turn(i + 1, p, lab(i + 1), NOTOOLS if i == 14 else LEAN)
    rec["sessions"].append(sid)
    rec["compaction_events"] = {s: updates_events(cwd, s) for s in rec["sessions"] if s}
    json.dump(rec, open(out, "w"), indent=1); os.remove(out + ".part")
    shutil.rmtree(cwd, ignore_errors=True)
    return rec

if __name__ == "__main__":
    arms = os.environ.get("ARMS", "full,compact,manual").split(",")
    reps = [int(x) for x in os.environ.get("REPS", "1,2").split(",")]
    jobs = [(a, r) for r in reps for a in arms]
    hit = False
    with cf.ThreadPoolExecutor(int(os.environ.get("PAR", "6"))) as ex:
        futs = {ex.submit(run_arm, a, r): (a, r) for a, r in jobs}
        for f in cf.as_completed(futs):
            try:
                rec = f.result(); print(futs[f], "done", sum(t["ok"] for t in rec["turns"]), "/", len(rec["turns"]), flush=True)
            except QuotaHit as e:
                hit = True; print("QUOTA HIT", futs[f], e, flush=True)
            except Exception as e:
                print("ERR", futs[f], repr(e), flush=True)
    sys.exit(3 if hit else 0)
