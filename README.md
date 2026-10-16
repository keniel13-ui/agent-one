# Agent One

A small personal AI agent that runs on a regular Mac with a free local model, and **cannot** post, send, delete or rewrite its own memory, because the code doesn't give it a way to. Not because it was asked nicely.

It's the first working piece of a companion + guardian agent I'm building in public. It's early, and the limits below are real.

## What it does
- **Talks with you** in a terminal, using a local model through [Ollama](https://ollama.com) (`llama3.2` by default). No paid model API and no per-call model charge. The model works offline; the DEV lookup needs internet.
- **Looks things up with three read-only tools:** your latest public DEV articles, your mission file, and its own memory. Any tool name not on that list is refused and logged.
- **Names its sources.** Every answer ends with a sources line written by the program from its own tool receipts, not by the model.
- **Remembers across restarts.** Memory has kinds that are kept apart:
  - `preference` and `proposal`: saved **only by you**, with `/remember preference: ...` or `/remember proposal: ...`. The model has no tool that writes memory.
  - `observation`: written only by code, from structured tool results (the daily job).
  - decisions are never stored in memory. The agent treats something as decided only if it's in a separate owner decision record (`~/.team/DECISIONS.md` in my setup, written by a keyboard-only command). No record means undecided.
- **Has a daily job that can be scheduled with cron** (the first unattended run is still pending): `--daily` compares your latest 10 DEV articles with the last check and writes a report.
  - The facts come from code.
  - It doesn't read comment text, so the report says that the content and importance of a new comment are **unknown**, instead of guessing.
  - A failed fetch writes a failure report and changes nothing.
- **Logs everything** to `logs/events.jsonl`: every tool call with its source and the data returned, every refusal, every memory save or removal, and every start and stop.

## Run it
```bash
ollama pull llama3.2
python3 companion.py                 # chat (type quit to exit)
python3 companion.py --ask "Which of my recent DEV articles has the most comments?"
python3 companion.py --selftest      # proves an unlisted tool ('publish_post') is refused and logged
python3 companion.py --daily         # the daily check; writes reports/<date_time>.md
python3 companion.py --forget <id>   # remove one memory; the removed entry is logged in full
```
Change `DEV_USER` in `companion.py` to your own DEV username.

## Schedule it (optional)
`bash install_schedule.sh [HH:MM]` adds **one** line to your crontab (default 09:05).
- It makes an exact backup first. If it can't read your crontab or can't save the backup, it stops before writing anything.
- Before installing, it proves the new crontab is your exact original plus one line.
- After installing, it compares byte for byte. If anything differs it restores your backup, checks the restore, and says `RESTORE FAILED` plainly if the restore didn't work.
- Running it twice does nothing the second time.
- It prints an undo command.

The script uses my Python path; edit `PY=` for yours. Cron only runs while the Mac is awake.

## Known limits (honest list)
- **Slow:** about 1–4 minutes per answer with `llama3.2` on a 2019-era MacBook.
- **The small model words uncertainty badly.** Given a memory that says "undecided" and a rule that says "never answer yes or no", it still answered "not yet". The facts it's given are right; its wording isn't always.
- **Read-only on purpose.** It can't act on anything yet. Security testing (tricky instructions hidden in data, forbidden actions, failures mid-run) hasn't been done.
- **The decision record checks hash-chain consistency, not authorship.** Another process running as your user could replace it and compute a new valid chain. The real boundary right now is that the agent has no write tools.
- Unattended operation: the first scheduled run is 2026-10-17. Until it has run on its own for a few days, treat "runs on its own" as unproven.
