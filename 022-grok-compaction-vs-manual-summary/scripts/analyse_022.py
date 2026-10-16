# Score the final quiz (turn 12) and the snippet (turn 11); sum tokens/cost per arm; draw chart.png
import json, os, re, glob, statistics as st
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = {  # regex on the answer line, case-insensitive; verified against fixture/itsdangerous (commit 672971d)
    1: r"itsdangerous\.signer", 2: r"django-concat", 3: r"(?=.*\bconcat)(?=.*django-concat)(?=.*hmac)(?=.*none)",
    4: r"^\W*b?['\"]?itsdangerous['\"]?\W*$|b?['\"]itsdangerous['\"]", 5: r"json", 6: r"signatureexpired", 7: r"utc",
    8: r"['\"`]?\.['\"`]?|dot|period", 9: r"zlib", 10: r"baddata", 11: r"badtimesignature", 12: r"3\.10",
    13: r"2024-04-16|april 16,? 2024|16 april 2024", 14: r"['\"`]?-['\"`]?|hyphen|dash", 15: r"\b11\b", 16: r"\b13\b",
    17: r"test_fallback_signers", 18: r"freezegun", 19: r"date_signed", 20: r"sha-?512", 21: r"\b(3|three)\b",
}
PRE, POST = range(1, 14), range(14, 22)
def parse(text):
    a = {}
    for line in (text or "").splitlines():
        for part in re.split(r"(?=\bF\d+\s*:)", line):
            m = re.match(r"^\W*F(\d+)\s*[:.)-]\s*(.*)$", part)
            if m: a.setdefault(int(m.group(1)), m.group(2).strip())
    return a
def score(ans):
    s = {}
    for k, g in GOLD.items():
        v = ans.get(k, "")
        if k == 4 and re.search(r"signer", v, re.I): s[k] = 0; continue  # 'itsdangerous.Signer' is F1, not F4
        if k == 1 and not re.search(r"itsdangerous\.signer", v, re.I): s[k] = 0; continue
        s[k] = int(bool(v) and bool(re.search(g, v, re.I)))
    return s
def snippet(t):
    t = t or ""
    checks = dict(cls="URLSafeTimedSerializer" in t, salt=bool(re.search(r"salt\s*=\s*['\"]reset", t)),
                  max_age=bool(re.search(r"max_age\s*=\s*(3600|60\s*\*\s*60)", t)), expired="SignatureExpired" in t, badsig="BadSignature" in t,
                  order=(t.find("except SignatureExpired") < t.find("except BadSignature")) if ("except SignatureExpired" in t and "except BadSignature" in t) else False)
    return checks
# Compaction runs on a side call whose usage the CLI does NOT report. Rough API-equivalent bounds from the CLI's own rates
# (fitted exactly from grok_calls.csv: $0.68/M uncached input, $0.17/M cached input, $2.04/M output):
# low = summary input all cached; high = all uncached. tokens_after taken as the summary's output size.
def comp_cost(ev):
    lo = hi = 0.0; n = 0
    for evs in (ev or {}).values():
        for e in evs:
            if e.get("sessionUpdate") == "auto_compact_completed":
                b, a = e.get("tokens_before", 0), e.get("tokens_after", 0); n += 1
                lo += b * 0.17e-6 + a * 2.04e-6; hi += b * 0.68e-6 + a * 2.04e-6
    return n, lo, hi
rows = []
for f in sorted(g for g in glob.glob(f"{D}/results/session_*_r*.json") if "session_v2_" not in g):
    r = json.load(open(f)); T = r["turns"]
    quiz = next(t for t in T if t["turn"] == 12); snip = next(t for t in T if t["turn"] == 11)
    # per-turn in-context answers (what the model said right after reading the file)
    inturn = {}
    for t in T:
        if isinstance(t["turn"], int) and t["turn"] <= 10: inturn.update(parse(t["text"]))
    sq, si = score(parse(quiz["text"])), score(inturn)
    sn = snippet(snip["text"])
    rows.append(dict(arm=r["arm"], rep=r["rep"], calls=len(T) + (1 if "compaction_call" in r else 0), failed=sum(1 - t["ok"] for t in T),
                     total_input=sum(t["total_in"] for t in T), uncached_input=sum(t["input"] for t in T), output=sum(t["out"] for t in T),
                     cost=sum(float(t["cost"] or 0) for t in T), cost_t7_12=sum(float(t["cost"] or 0) for t in T if t["turn"] >= 7),
                     in_t12=quiz["total_in"], in_t7=next(t for t in T if t["turn"] == 7)["total_in"],
                     quiz_pre=sum(sq[k] for k in PRE), quiz_post=sum(sq[k] for k in POST), quiz_all=sum(sq.values()),
                     inturn_all=sum(si.values()), snippet=sum(sn.values()), snippet_checks=sn, quiz_wrong={k: parse(quiz["text"]).get(k, "") for k in GOLD if not sq[k]},
                     compaction=r.get("compaction_events"), compaction_call=r.get("compaction_call"),
                     handoff_chars=len(r.get("handoff_note", "") or ""), per_turn_in=[(t["turn"], t["total_in"]) for t in T]))
    n, lo, hi = comp_cost(r.get("compaction_events")); rows[-1].update(compactions=n, hidden_comp_lo=lo, hidden_comp_hi=hi, cost_adj_lo=rows[-1]["cost"] + lo, cost_adj_hi=rows[-1]["cost"] + hi)
json.dump(rows, open(f"{D}/results/scores.json", "w"), indent=1)
arms = [a for a in ["full", "compact", "manual", "auto"] if any(r["arm"] == a for r in rows)]
summ = {}
for a in arms:
    R = [r for r in rows if r["arm"] == a]
    summ[a] = {k: round(st.mean(r[k] for r in R), 5) for k in ["total_input", "uncached_input", "output", "cost", "cost_t7_12", "in_t7", "in_t12", "quiz_pre", "quiz_post", "quiz_all", "inturn_all", "snippet", "failed", "compactions", "hidden_comp_lo", "hidden_comp_hi", "cost_adj_lo", "cost_adj_hi"]}
    summ[a]["n"] = len(R)
json.dump(summ, open(f"{D}/results/summary.json", "w"), indent=1)
for a, s in summ.items(): print(a, s)
for r in rows: print(r["arm"], r["rep"], "quiz", r["quiz_all"], "wrong", r["quiz_wrong"], "compaction", r["compaction"])
# chart
lab = {"full": "No compaction\n(12 resumed turns)", "compact": "Built-in /compact\nafter turn 6", "manual": "Manual handoff note\n-> fresh session", "auto": "Auto-compact\n(threshold lowered)"}
col = {"full": "#4C72B0", "compact": "#DD8452", "manual": "#55A868", "auto": "#C44E52"}
fig, ax = plt.subplots(1, 3, figsize=(16, 5))
for a in arms:
    for r in [r for r in rows if r["arm"] == a]:
        xs = [t for t, _ in r["per_turn_in"]]; ys = [v / 1000 for _, v in r["per_turn_in"]]
        ax[0].plot(xs, ys, "-o", ms=3, color=col[a], alpha=.8, label=lab[a].replace("\n", " ") if r["rep"] == 1 else None)
ax[0].set_xlabel("turn (6.5 = handoff-note call)"); ax[0].set_ylabel("input tokens sent per turn (K, incl. cached)"); ax[0].set_title("Context size per turn"); ax[0].legend(fontsize=8)
x = range(len(arms))
ax[1].bar(x, [summ[a]["cost"] * 100 for a in arms], color=[col[a] for a in arms]); ax[1].set_xticks(list(x)); ax[1].set_xticklabels([lab[a] for a in arms], fontsize=8)
ax[1].set_ylim(0, max(summ[a]["cost_adj_hi"] for a in arms) * 118); ax[1].set_ylabel("US cents per 12-turn session (API-equivalent est.)"); ax[1].set_title("Cost per session (mean of reps)")
ax[1].bar(x, [(summ[a]["cost_adj_hi"] - summ[a]["cost"]) * 100 for a in arms], bottom=[summ[a]["cost"] * 100 for a in arms], color="none", edgecolor="k", hatch="..", label="est. hidden compaction cost (upper bound)")
for i, a in enumerate(arms): ax[1].text(i, summ[a]["cost_adj_hi"] * 100 + .3, f"{summ[a]['cost']*100:.1f}¢" + (f" (+{summ[a]['hidden_comp_lo']*100:.1f}-{summ[a]['hidden_comp_hi']*100:.1f})" if summ[a]["compactions"] else ""), ha="center", fontsize=8)
ax[1].legend(fontsize=7, loc="lower right")
w = .38
ax[2].bar([i - w / 2 for i in x], [summ[a]["quiz_pre"] / 13 * 100 for a in arms], w, color=[col[a] for a in arms], label="facts from turns 1-6 (13)")
ax[2].bar([i + w / 2 for i in x], [summ[a]["quiz_post"] / 8 * 100 for a in arms], w, color=[col[a] for a in arms], alpha=.5, hatch="//", label="facts from turns 7-10 (8)")
ax[2].set_xticks(list(x)); ax[2].set_xticklabels([lab[a] for a in arms], fontsize=8); ax[2].set_ylim(0, 110); ax[2].set_ylabel("final-quiz recall (%)"); ax[2].set_title("Turn-12 quiz from memory"); ax[2].legend(fontsize=8, loc="lower right")
for i, a in enumerate(arms):
    ax[2].text(i - w / 2, summ[a]["quiz_pre"] / 13 * 100 + 1, f"{summ[a]['quiz_pre']:.1f}", ha="center", fontsize=8)
    ax[2].text(i + w / 2, summ[a]["quiz_post"] / 8 * 100 + 1, f"{summ[a]['quiz_post']:.1f}", ha="center", fontsize=8)
fig.suptitle("#022 Grok Build CLI: 12-turn codebase audit (itsdangerous) - compaction vs manual handoff")
plt.tight_layout(); plt.savefig(f"{D}/chart.png", dpi=120)

# ---------------- v2 hard task ----------------
GOLD2 = {1: r"^\D*76\b", 2: r"_make_keys_list", 3: r"unknown key derivation method", 4: r"^\D*40\b", 5: r"is_text_serializer", 6: r"itsdangerous(?!\.)",
         7: r"^\D*170\b", 8: r"timestamp missing", 9: r"signature age \{age\} > \{max_age\} seconds", 10: r"^\D*79\b", 11: r"zlib", 12: r"urlsafeserializermixin",
         13: r"^\D*66\b", 14: r"baddata", 15: r"badsignature", 16: r"invalid base64-encoded data", 17: r"int_to_bytes", 18: r"^\D*28\b",
         19: r"_compactjson", 20: r"['\"],['\"]\s*,\s*['\"]:['\"]", 21: r"^\D*17\b", 22: r"2022-03-24", 23: r"2021-05-11", 24: r"2022-02-17",
         25: r"flit_core\.buildapi", 26: r"3\.10", 27: r"tests", 28: r"1\.5\.2", 29: r"8\.3\.5", 30: r"^\D*69\b",
         31: r"['\"`]-['\"`]|^\W*-\W*$|hyphen|dash", 32: r"^\D*11\b", 33: r"^\D*94\b", 34: r"^\D*13\b", 35: r"^\D*186\b", 36: r"test_fallback_signers",
         37: r"freezegun", 38: r"date_signed", 39: r"^\D*96\b", 40: r"sha-?512", 41: r"\b(3|three)\b", 42: r"\b(4|four)\b"}
def parse2(text):
    a = {}
    for line in (text or "").splitlines():
        for part in re.split(r"(?=\bH\d+\s*:)", line):
            m = re.match(r"^\W*H(\d+)\s*[:.)-]\s*(.*)$", part)
            if m: a.setdefault(int(m.group(1)), m.group(2).strip())
    return a
def score2(ans):
    return {k: int(bool(ans.get(k)) and bool(re.search(g, ans.get(k, ""), re.I))) for k, g in GOLD2.items()}
rows2 = []
for f in sorted(glob.glob(f"{D}/results/session_v2_*_r*.json")):
    r = json.load(open(f)); T = r["turns"]; quiz = next(t for t in T if t["turn"] == 15)
    inturn = {}
    for t in T:
        if t["turn"] <= 14: inturn.update(parse2(t["text"]))
    sq, si = score2(parse2(quiz["text"])), score2(inturn)
    rows2.append(dict(arm=r["arm"], rep=r["rep"], calls=len(T), failed=sum(1 - t["ok"] for t in T), total_input=sum(t["total_in"] for t in T),
                      uncached_input=sum(t["input"] for t in T), output=sum(t["out"] for t in T), cost=sum(float(t["cost"] or 0) for t in T),
                      cost_t9_15=sum(float(t["cost"] or 0) for t in T if t["turn"] >= 9), in_t9=next(t for t in T if t["turn"] == 9)["total_in"],
                      quiz_pre=sum(sq[k] for k in range(1, 25)), quiz_post=sum(sq[k] for k in range(25, 43)), quiz_all=sum(sq.values()),
                      inturn_all=sum(si.values()), lost_vs_inturn=[k for k in GOLD2 if si[k] and not sq[k]],
                      quiz_wrong={k: parse2(quiz["text"]).get(k, "") for k in GOLD2 if not sq[k]}, inturn_wrong={k: inturn.get(k, "") for k in GOLD2 if not si[k]},
                      compaction=r.get("compaction_events"), compaction_call=r.get("compaction_call"), handoff_chars=len(r.get("handoff_note", "") or ""),
                      per_turn_in=[(t["turn"], t["total_in"]) for t in T]))
    n, lo, hi = comp_cost(r.get("compaction_events")); rows2[-1].update(compactions=n, hidden_comp_lo=lo, hidden_comp_hi=hi, cost_adj_lo=rows2[-1]["cost"] + lo, cost_adj_hi=rows2[-1]["cost"] + hi)
if rows2:
    json.dump(rows2, open(f"{D}/results/scores_v2.json", "w"), indent=1)
    arms2 = [a for a in ["full", "compact", "manual", "auto"] if any(r["arm"] == a for r in rows2)]
    summ2 = {}
    for a in arms2:
        R = [r for r in rows2 if r["arm"] == a]
        summ2[a] = {k: round(st.mean(r[k] for r in R), 5) for k in ["total_input", "uncached_input", "output", "cost", "cost_t9_15", "in_t9", "quiz_pre", "quiz_post", "quiz_all", "inturn_all", "failed", "compactions", "hidden_comp_lo", "hidden_comp_hi", "cost_adj_lo", "cost_adj_hi"]}
        summ2[a]["n"] = len(R)
    json.dump(summ2, open(f"{D}/results/summary_v2.json", "w"), indent=1)
    print("\nV2"); [print(a, s) for a, s in summ2.items()]
    for r in rows2: print(r["arm"], r["rep"], "quiz", r["quiz_all"], "inturn", r["inturn_all"], "lost", r["lost_vs_inturn"], "comp", r["compaction"])
    fig, ax = plt.subplots(1, 3, figsize=(16, 5))
    for a in arms2:
        for r in [r for r in rows2 if r["arm"] == a]:
            ax[0].plot([t for t, _ in r["per_turn_in"]], [v / 1000 for _, v in r["per_turn_in"]], "-o", ms=3, color=col[a], alpha=.8, label=lab[a].replace("\n", " ").replace("turn 6", "turn 8").replace("12 resumed", "15 resumed") if r["rep"] == 1 else None)
    ax[0].set_xlabel("turn (8.5 = handoff-note call)"); ax[0].set_ylabel("input tokens sent per turn (K, incl. cached)"); ax[0].set_title("Context size per turn"); ax[0].legend(fontsize=8)
    x = range(len(arms2)); L2 = [lab[a].replace("turn 6", "turn 8").replace("12 resumed", "15 resumed") for a in arms2]
    ax[1].bar(x, [summ2[a]["cost"] * 100 for a in arms2], color=[col[a] for a in arms2]); ax[1].set_xticks(list(x)); ax[1].set_xticklabels(L2, fontsize=8)
    ax[1].set_ylim(0, max(summ2[a]["cost_adj_hi"] for a in arms2) * 118); ax[1].set_ylabel("US cents per 15-turn session (API-equivalent est.)"); ax[1].set_title("Cost per session (mean of reps)")
    ax[1].bar(x, [(summ2[a]["cost_adj_hi"] - summ2[a]["cost"]) * 100 for a in arms2], bottom=[summ2[a]["cost"] * 100 for a in arms2], color="none", edgecolor="k", hatch="..", label="est. hidden compaction cost (upper bound)")
    for i, a in enumerate(arms2): ax[1].text(i, summ2[a]["cost_adj_hi"] * 100 + .6, f"{summ2[a]['cost']*100:.1f}¢" + (f" (+{summ2[a]['hidden_comp_lo']*100:.1f}-{summ2[a]['hidden_comp_hi']*100:.1f})" if summ2[a]["compactions"] else ""), ha="center", fontsize=8)
    ax[1].legend(fontsize=7, loc="lower right")
    w = .38
    ax[2].bar([i - w / 2 for i in x], [summ2[a]["quiz_pre"] / 24 * 100 for a in arms2], w, color=[col[a] for a in arms2], label="facts from turns 1-8 (24)")
    ax[2].bar([i + w / 2 for i in x], [summ2[a]["quiz_post"] / 18 * 100 for a in arms2], w, color=[col[a] for a in arms2], alpha=.5, hatch="//", label="facts from turns 9-14 (18)")
    ax[2].set_xticks(list(x)); ax[2].set_xticklabels(L2, fontsize=8); ax[2].set_ylim(0, 115); ax[2].set_ylabel("final-quiz recall (%)"); ax[2].set_title("Turn-15 quiz from memory (42 detail facts)"); ax[2].legend(fontsize=8, loc="lower right")
    for i, a in enumerate(arms2):
        ax[2].text(i - w / 2, summ2[a]["quiz_pre"] / 24 * 100 + 1, f"{summ2[a]['quiz_pre']:.1f}", ha="center", fontsize=8)
        ax[2].text(i + w / 2, summ2[a]["quiz_post"] / 18 * 100 + 1, f"{summ2[a]['quiz_post']:.1f}", ha="center", fontsize=8)
    fig.suptitle("#022 hard variant: 15-turn audit, 42 detail facts (line numbers, exact messages, versions)")
    plt.tight_layout(); plt.savefig(f"{D}/chart_v2.png", dpi=120)
