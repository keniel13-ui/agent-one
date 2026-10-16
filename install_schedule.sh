#!/bin/bash
# Adds ONE line to Keniel's crontab so Agent One's daily DEV check runs on its own. Every existing line is kept.
# Usage: bash ~/companion/install_schedule.sh [HH:MM]   (default 09:05, local time)
# Safety order: (1) read the crontab into an exact backup file; stop if that fails or the backup is not an exact copy;
# (2) install old contents + one line; (3) compare byte-for-byte with what was expected; if different, restore the
# backup and CHECK the restore, reporting plainly if the restore failed. Undo any time: crontab <backup file>.
set -u
TIME="${1:-09:05}"; H="${TIME%%:*}"; M="${TIME##*:}"
PY=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
DIR="${AGENT_ONE_BACKUP_DIR:-$HOME/companion/state}"      # override only for tests
B="$DIR/crontab.backup-$(date +%Y%m%d-%H%M%S)"
WORK=$(mktemp -d) || { echo "STOP: no temp space. Nothing changed."; exit 1; }
LINE="$((10#$M)) $((10#$H)) * * * cd $HOME/companion && $PY companion.py --daily >> $HOME/companion/logs/cron.log 2>&1 # agent-one-daily"

# 1. Exact backup, or stop before writing anything.
HAD_CRONTAB=1
if ! crontab -l > "$WORK/current" 2> "$WORK/err"; then
  if grep -qi "no crontab for" "$WORK/err"; then HAD_CRONTAB=0; : > "$WORK/current"
  else echo "STOP: could not read your current crontab ($(cat "$WORK/err")). Nothing changed."; exit 1; fi
fi
if ! mkdir -p "$DIR" 2>/dev/null || ! cp "$WORK/current" "$B" 2>/dev/null || ! cmp -s "$WORK/current" "$B"; then
  echo "STOP: could not save an exact backup to $DIR. Nothing changed."; exit 1
fi
if grep -q "# agent-one-daily" "$B"; then echo "Already installed (found # agent-one-daily). Nothing changed."; exit 0; fi

# 2. Expected result = the exact old contents (with a final newline) + the one line. Every step is checked, and the
#    result must provably START with the exact backup bytes and be exactly one line longer, before anything installs.
cp "$B" "$WORK/expected" || { echo "STOP: could not prepare the new schedule. Nothing changed."; exit 1; }
if [ -s "$WORK/expected" ] && [ -n "$(tail -c 1 "$WORK/expected")" ]; then
  echo >> "$WORK/expected" || { echo "STOP: could not prepare the new schedule. Nothing changed."; exit 1; }
fi
echo "$LINE" >> "$WORK/expected" || { echo "STOP: could not prepare the new schedule. Nothing changed."; exit 1; }
BSIZE=$(wc -c < "$B" | tr -d ' ')
if ! head -c "$BSIZE" "$WORK/expected" | cmp -s - "$B" \
   || [ "$(wc -l < "$WORK/expected" | tr -d ' ')" -ne $(( $(wc -l < "$B" | tr -d ' ') + 1 + ( BSIZE > 0 && $(tail -c 1 "$B" | wc -l) == 0 ? 1 : 0 ) )) ] \
   || [ "$(tail -n 1 "$WORK/expected")" != "$LINE" ]; then
  echo "STOP: the new schedule does not contain your complete original plus exactly one line. Nothing changed."; exit 1
fi
echo "Current crontab: $(wc -l < "$B" | tr -d ' ') lines, backed up exactly to: $B"
echo "Adding exactly this line:"; echo "  $LINE"

# 3. Install and compare byte for byte.
if crontab "$WORK/expected" 2> "$WORK/err" && crontab -l > "$WORK/after" 2>/dev/null && cmp -s "$WORK/expected" "$WORK/after"; then
  echo "OK: installed. Your crontab is exactly the old contents plus that one line."
  echo "Agent One will check your DEV articles every day at $TIME (only while the Mac is awake)."
  echo "Undo: crontab $B"
  exit 0
fi
echo "PROBLEM: the installed crontab is not what was expected. Restoring your backup..."
if [ "$HAD_CRONTAB" -eq 1 ]; then crontab "$B" 2>/dev/null; else crontab -r 2>/dev/null; : ; fi
if crontab -l > "$WORK/restored" 2>/dev/null || [ "$HAD_CRONTAB" -eq 0 ]; then :; fi
if cmp -s "$B" "$WORK/restored" || { [ "$HAD_CRONTAB" -eq 0 ] && [ ! -s "$WORK/restored" ]; }; then
  echo "RESTORED: your crontab is back exactly as it was. Nothing changed."
else
  echo "RESTORE FAILED: your crontab may be wrong right now. Your exact original is saved at: $B"
  echo "Fix it with: crontab $B"
fi
exit 1
