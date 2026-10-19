# CLAUDE.md

Agent One is one Python file (`companion.py`, stdlib only) plus a cron installer (`install_schedule.sh`).
The product is a safety property: **the model cannot post, send, delete or write memory**. Keep it that way.

## Rules for changes
- The model's only reach is `run_tool()` through the `TOOLS` allowlist (`read_mission`, `dev_articles`, `recall`).
  Never add a tool that writes, sends or deletes. `test_companion.py` pins the allowlist and fails if it grows.
- Memory is written only by the owner (`/remember`, `--forget`) or by code (`daily()` observations).
  `add_memory` refuses any kind outside `MEMORY_KINDS`; "decision" is deliberately absent.
- Treat everything the model returns (tool names, arguments, text) and everything fetched (DEV titles) as data.
- Rewrite files with `write_atomic()`, never `open(path, "w")` on state, memory or reports.
- Stay stdlib only and small. No new dependencies.

## Commands
```bash
python3 -m unittest -v          # adversarial + regression tests; fake model, no network, temp dirs only
python3 companion.py --selftest # needs no model: proves an unlisted tool is refused and logged
bash -n install_schedule.sh     # syntax check (running it edits your real crontab)
```
Real runs need Ollama (`ollama pull llama3.2`) and write `logs/`, `memory/`, `state/`, `reports/` next to the script.
