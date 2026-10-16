# Writeup: #022 Claude compaction vs manual summary

I built a 15-turn resumed Claude Code session (Sonnet, headless, no tools). Each turn planted one fact in about 750 words of filler. At turn 15 I branched three ways: keep going, run `/compact`, or have the model write a handoff note and start a fresh session with it. I ran 3 more turns and then quizzed all 15 facts. Each arm ran 3 times.

**All 9 sessions got 15/15.** Neither compaction method lost a fact. To be fair, my test was too easy to show any difference: the facts were labelled "KEY FACT" and the context was only about 30K tokens.

**Over a short tail, keeping the session going was cheapest.** From the branch point to the quiz it cost $0.031, against $0.038 for the manual handoff and $0.059 for `/compact` (API-equivalent). Prompt caching makes re-reading 30K tokens cost under a cent a turn, so compacting only pays back over a longer tail. Extrapolating the per-turn costs, the handoff breaks even after about 7 more turns and `/compact` after about 20. I didn't run those longer tails.

The handoff beat `/compact` on both counts. It was cheaper to make ($0.015 vs $0.027) and produced a smaller context (7.4K vs 8.5K at the quiz). The handoff prompt explicitly said to keep facts verbatim, and the note came out as a neat numbered list.

The finding that mattered most is about measurement. `total_cost_usd` is cumulative per resumed session, so my first pass summed running totals and overstated costs by about 10×. I caught it because the fresh-session arm's "per-call" costs kept climbing. `/compact` also reports zero usage, so its cost shows up only as a jump in the running total. Anyone summing `total_cost_usd` across `--resume` calls should check for this.

If I had more time, I'd run longer tails (20–40 turns) and plant facts without labels in realistic text. Then recall could actually separate the arms.
