# #022 Grok compaction vs manual summaries in long multi-turn sessions

**Engine:** Grok Build CLI 1.0.52 (SuperGrok, model reported `grok-4.7-build`) only. No engine swap was needed. Costs are **API-equivalent estimates** from the CLI's `total_cost_usd`. On SuperGrok the real limit is the usage window, not dollars.

**Question.** In a long, resumed (`grok -r <session>`) headless session doing a codebase audit, what is the cheapest way to keep context under control without losing answers? We compared four ways:
1. **full**: keep resuming the same session, no compaction
2. **compact**: run the built-in `/compact` once mid-session (as a headless prompt: `grok -r <id> -p "/compact"`)
3. **manual**: ask Grok for a compact handoff note, then continue in a **fresh** session seeded with that note
4. **auto**: built-in auto-compact, made to fire by lowering `[session] auto_compact_threshold_percent` in `~/.grok/config.toml` (8% ≈ 20K tokens for the easy task, 20% ≈ 51K for the hard task; the default is 85% of a 256K window, which these sessions never reach)

**Answer, short.**
- **Quality: no difference.** Every arm recalled essentially everything in the final from-memory quiz: 21/21 facts on the easy task (12 sessions) and 41–42 of 42 detail facts on the hard task (8 sessions). The only quiz misses were 1 answer per session, and the same mistake was already in that session's in-turn answer (e.g. a line number off by one), so no fact was lost *because of* compaction.
- **Cost: manual handoff is the safest saving.** On the hard task (one 1,186-line file read in turn 10 balloons context to ~200K+), manual handoff cost **38.9¢** vs **53.3¢** for no compaction (**−27%**). `/compact` saved less (44.7¢ + ~1.8–2.9¢ hidden). On the easy 12-turn task all arms land at 9–11¢ and the savings are within noise.
- **Auto-compact looks cheapest on the meter but isn't proven cheaper.** Its visible cost was 26.5¢ on the hard task, but it compacted 4 times per session (1 attempt failed), and **the CLI does not report compaction calls in `usage` or `total_cost_usd`** (its docs say so). Our estimate of that hidden cost is 12–24¢, so auto's true total is roughly 39–50¢, between manual and no compaction.

## Setup
- **Fixture:** public repo [`pallets/itsdangerous`](https://github.com/pallets/itsdangerous) at commit `672971d66a2ef9f85151e53283113f33d642dabd` (shallow clone, `.git` removed) in `fixture/itsdangerous/`. Each session works on its own copy.
- **Lean flags on every turn:** `--system-prompt-override "You are a careful code auditor ... Use the read_file tool ... Be brief." --disable-web-search --no-subagents --tools read_file`. The final quiz turn also passes `--disallowed-tools read_file` so it must answer from memory.
- **Easy task (v1), 12 turns, 3 reps per arm:** turns 1–10 each read one file and answer 2–3 short questions (21 facts F1–F21: defaults, exception classes, release date, test counts…). Turn 11 writes a 12-line code snippet from memory. Turn 12 is a from-memory quiz on all 21 facts. Compaction/handoff happens after turn 6.
- **Hard task (v2), 15 turns, 2 reps per arm:** turns 1–14 read one file each and answer 3 detail questions (42 facts H1–H42: line numbers, exact error messages, locked versions in `uv.lock`, release dates…). Turn 15 is the from-memory quiz. Compaction/handoff happens after turn 8.
- **Scoring:** regex per fact against gold values checked by hand against the fixture (`scripts/analyse_022.py`, `GOLD` and `GOLD2`). Snippet scored on 6 checks (right class, salt, max_age, both exceptions, except-order).
- **Hidden compaction cost estimate:** from the session's `auto_compact_completed` events (`tokens_before`, `tokens_after`) priced at the CLI's own rates, which we fitted exactly from the logged calls ($0.68/M uncached input, $0.17/M cached input, $2.04/M output; max error 1e-15). Low bound = summary input all cached; high bound = all uncached. It ignores reasoning tokens in the compaction call, so the real figure could be higher.
- Run 2026-10-15, 01:06–01:46 IST.

```bash
source /workspace/tools/setup.sh
PY=/workspace/tools/mlenv/bin/python
REPS=1,2,3 $PY scripts/run_022.py                    # v1: full, compact, manual
TASK=v2 REPS=1,2 $PY scripts/run_022.py              # v2: full, compact, manual
# auto arm: temporarily add to ~/.grok/config.toml ->  [session] auto_compact_threshold_percent = 8   (v1) / 20 (v2)
ARMS=auto REPS=1,2,3 $PY scripts/run_022.py; TASK=v2 ARMS=auto REPS=1,2 $PY scripts/run_022.py   # then remove the setting
$PY scripts/analyse_022.py                           # -> results/summary*.json, scores*.json, chart.png, chart_v2.png
```

## Results

**Hard task (v2, 15 turns, 42 facts, 2 reps per arm)** – `chart_v2.png`

| arm | visible cost / session | + hidden compaction (est.) | input tokens at turn 9 | quiz (of 42) | compactions |
|---|---|---|---|---|---|
| full (no compaction) | 53.3¢ | 0 | 44.9K | 42.0 | 0 |
| `/compact` after turn 8 | 44.7¢ | +1.8–2.9¢ | 20.2K | 41.5 | 1 |
| **manual handoff → fresh session** | **38.9¢** | 0 (the note is a normal, metered turn) | 17.0K | 41.5 | 0 |
| auto-compact at 20% (~51K) | 26.5¢ | +12.2–23.8¢ | 44.3K | 41.5 | 4 (+1 failed) |

**Easy task (v1, 12 turns, 21 facts, 3 reps per arm)** – `chart.png`

| arm | visible cost / session | + hidden compaction (est.) | input tokens at turn 7 | quiz (of 21) | snippet (of 6) |
|---|---|---|---|---|---|
| full | 10.8¢ | 0 | 40.4K | 21 | 6 |
| `/compact` after turn 6 | 9.3¢ | +1.7–2.6¢ | 18.0K | 21 | 6 |
| manual handoff | 9.9¢ | 0 | 12.5K | 21 | 6 |
| auto-compact at 8% (~20K) | 9.7¢ | +1.9–3.0¢ | 39.4K → 21.6K after | 21 | 6 |

Other numbers:
- `/compact` in headless mode works: it returns an empty JSON result (no `usage`, no cost) after ~30–53 s and writes `auto_compact_completed` with `tokens_before`≈18–21K → `tokens_after`≈6–7K into the session's `updates.jsonl`.
- `grok usage <session>` agrees exactly with the summed per-turn `total_cost_usd` and also does **not** include the compaction call.
- The manual handoff notes were ~880 characters (≈250 tokens), and Grok put every fact so far into them verbatim.
- In the hard task, turn 10 (`uv.lock`, 1,186 lines) is where cost explodes: every arm's next turns carry ~180–215K input tokens, and that file stays in context until something removes it. Manual handoff and `/compact` happened *before* that turn, so they only saved the earlier context. Auto-compact fired right after it and cut context back to ~23K, which is why its visible bill is so low.
- In one v2 `/compact` session, turns 10–11 took 212 s and 240 s (8 model calls in turn 10); other arms took 10–40 s for the same turn. Treat that as one slow outlier.
- 0 failed calls, 0 limit hits; total metered spend for this repo $5.51 API-equivalent (includes a v2 attempt aborted by a sandbox restart, kept in `results/aborted_v2_attempt1/`).

## Caveats
- **Small n:** 3 reps (easy) and 2 reps (hard) per arm. Cost differences on the easy task (9–11¢) are within rep-to-rep noise; the hard-task gap between full (53¢) and manual (39¢) is consistent across both reps.
- **The quiz was too easy for this model.** Grok kept all facts through every kind of compaction, so this test can't separate the arms on quality. Compaction may lose more on longer sessions, vaguer facts, or facts that are only implied by tool output.
- **Hidden compaction cost is our estimate,** not a metered figure. It's priced from token counts the CLI reports in the session log, not from a bill.
- **Auto-compact was forced** with a much lower threshold than the default 85% of 256K. At default settings these sessions would never auto-compact; you'd be in the "full" arm.
- Changing the threshold is a global config edit; it was restored right after the auto runs (`~/.grok/config.toml` now matches its original content).
- Costs are API-equivalent estimates. SuperGrok is billed as a subscription with a usage window.
