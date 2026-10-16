# Should you let your AI agent compact its own memory? I tested 4 ways on Grok

*Draft for Tech in General: real numbers, 15 Oct 2026.*

Long agent sessions get expensive because every new turn re-sends the whole conversation. After a dozen turns of reading files, each message can carry 200,000 tokens of history. There are three common fixes:

- **Compact**: ask the agent to squash its history into a summary (`/compact` in Grok Build)
- **Auto-compact**: let the agent do that by itself when the context fills up
- **Manual handoff**: ask the agent for a short handoff note, then start a fresh session with only that note

I tried all three against doing nothing, on a real open-source codebase (`itsdangerous`, the library Flask uses to sign cookies).

## The test

Grok audits the codebase over 12–15 turns, reading one file per turn and answering questions about it: line numbers, exact error messages, version numbers. On the last turn, with file access switched off, it has to recall **every** answer from memory. If compaction throws away details, it shows up there.

## Results (hard version: 15 turns, 42 facts)

| | cost per session | facts recalled |
|---|---|---|
| Do nothing | 53¢ | 42 / 42 |
| `/compact` mid-way | 45¢ + ~2¢ hidden | 41.5 / 42 |
| **Manual handoff note** | **39¢** | 41.5 / 42 |
| Auto-compact | 27¢ on the meter, **+12–24¢ hidden** | 41.5 / 42 |

*(Costs are API-equivalent estimates from the CLI. My SuperGrok plan has a usage limit, not a per-token bill.)*

## What I learned

**1. Grok didn't forget anything.** Every method kept virtually every fact. The half-point misses were mistakes it had already made when it first read the file, not facts lost in compaction. Grok's summaries are good.

**2. The handoff note was the safest saving: 27% cheaper.** One extra turn writes a ~250-token note, and the fresh session starts small. Every token is metered, so the saving is real.

**3. Auto-compact's bill is misleading.** It looked half the price, but the compaction itself runs on a side call the CLI doesn't count. Grok's own docs say that call is excluded from `usage`. The CLI's logs show each compaction squashing ~50–70K tokens down to ~10K, four times per session. Priced at the same rates, that adds 12–24¢, so it's probably no cheaper than a handoff note.

**4. One big file is what really costs you.** In turn 10 Grok read a 1,200-line lock file. From then on every turn carried ~200K tokens, whatever method I used, unless something removed that file from context. Keeping huge files out of a long session matters more than which compaction you pick.

## So what should you do?

- For long agent jobs, **ask for a handoff note and restart** at natural break points. It's cheap, the cost is visible, and it lost nothing here.
- Don't trust a cost meter that excludes the compaction calls.
- Keep large generated files (lock files, logs, minified code) out of a long session's context.

*Caveats: 2–3 runs per method; this quiz was too easy to separate them on quality; I forced auto-compact with a low threshold, since by default it only fires at 85% of a 256K window.*
