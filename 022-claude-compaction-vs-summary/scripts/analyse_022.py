# Score quiz recall and sum costs per arm; write results/scores.json, summary.json, chart.png
import json, glob, os, re, statistics as st, sys
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, f"{D}/scripts"); from run_022 import FACTS
rows = []
for f in sorted(glob.glob(f"{D}/results/raw/session_*.json")):
    r = json.load(open(f)); C = r["calls"]
    # total_cost_usd is CUMULATIVE per resumed session id -> per-call cost = delta within the same session
    prev = {}
    for c in C:
        c["dcost"] = (c["cost"] or 0) - prev.get(c["session"], 0); prev[c["session"]] = c["cost"] or 0
    ans = {}
    for line in C[-1]["text"].splitlines():
        m = re.match(r"^\W*Q(\d+)\W*[:.)-]\s*(.*)$", line.strip())
        if m: ans.setdefault(int(m.group(1)), m.group(2))
    hits = [int(bool(re.search(g, ans.get(k + 1, ""), re.I)) and "unknown" not in ans.get(k + 1, "").lower()) for k, (_, _, g) in enumerate(FACTS)]
    bi = next((i for i, c in enumerate(C) if c["label"] in ("compact", "handoff")), 15)
    rows.append(dict(arm=r["arm"], rep=r["rep"], recall=sum(hits), missed=[k + 1 for k, h in enumerate(hits) if not h],
                     cost_total=sum(c["dcost"] for c in C), cost_plant=sum(c["dcost"] for c in C[:15]),
                     cost_branch=sum(c["dcost"] for c in C[15:bi + (2 if r["arm"] == "manual" else 1 if r["arm"] == "compact" else 0)]),
                     cost_after=sum(c["dcost"] for c in C if c["label"].startswith("post") or c["label"] == "quiz"),
                     compact_hidden=sum(c["dcost"] for c in C if c["label"] == "compact"), ctx_quiz=C[-1]["ctx"], ctx_before_branch=C[14]["ctx"], ctx_series=[(c["label"], c["ctx"]) for c in C], errors=sum(1 for c in C if not c["session"])))
json.dump(rows, open(f"{D}/results/scores.json", "w"), indent=1)
arms = [a for a in ["full", "compact", "manual"] if any(r["arm"] == a for r in rows)]
summ = {a: {k: round(st.mean(r[k] for r in rows if r["arm"] == a), 4) for k in ["recall", "cost_total", "cost_plant", "cost_branch", "cost_after", "compact_hidden", "ctx_quiz", "ctx_before_branch", "errors"]} | {"n": sum(r["arm"] == a for r in rows)} for a in arms}
json.dump(summ, open(f"{D}/results/summary.json", "w"), indent=1)
for a, s in summ.items(): print(a, s)
for r in rows: print(r["arm"], r["rep"], r["recall"], r["missed"], round(r["cost_total"], 3), r["ctx_quiz"])
lab = {"full": "Keep going", "compact": "/compact", "manual": "Manual note → fresh"}
col = {"full": "#2a6fdb", "compact": "#e07b39", "manual": "#3a9a5b"}
fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
x = range(len(arms))
for i, a in enumerate(arms):
    R = [r for r in rows if r["arm"] == a]
    ax[0].bar(i, summ[a]["cost_branch"] + summ[a]["cost_after"], color=col[a])
    ax[0].scatter([i] * len(R), [r["cost_branch"] + r["cost_after"] for r in R], color="#222", s=12, zorder=3)
    ax[0].text(i, summ[a]["cost_branch"] + summ[a]["cost_after"], f"${summ[a]['cost_branch'] + summ[a]['cost_after']:.3f}\nrecall {summ[a]['recall']:.1f}/15", ha="center", va="bottom", fontsize=9)
    for r in R:
        ax[1].plot(*zip(*[(i, v / 1000) for i, (l, v) in enumerate(r["ctx_series"]) if l != "compact"]), color=col[a], alpha=.7, label=lab[a] if r is R[0] else None)
ax[0].set_xticks(list(x), [lab[a] for a in arms]); ax[0].set_ylabel("USD (API-equivalent est.)")
ax[0].set_title("Cost from branch point to quiz (incl. compaction/handoff)", fontsize=10)
ax[0].margins(y=.25); ax[0].spines[["top", "right"]].set_visible(False)
ax[1].set_xlabel("call # in session"); ax[1].set_ylabel("context tokens per call (K)\n(/compact call omitted: reports 0 usage)"); ax[1].legend(frameon=False)
ax[1].set_title("Context size per call", fontsize=10); ax[1].spines[["top", "right"]].set_visible(False)
fig.suptitle("#022 Claude Code (Sonnet, headless): 15 planted facts, then compaction strategy", fontsize=11)
fig.tight_layout(); fig.savefig(f"{D}/chart.png", dpi=130)
