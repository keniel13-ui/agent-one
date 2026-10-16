"""Agent One (M1, session 1): Keniel's companion + guardian, smallest runnable version.

Runs as its own process, outside Claude Code. Talks with Keniel in a terminal. Uses a local model (Ollama), so it
works offline and costs nothing. Every tool call is checked against an allowlist in code (not a prompt), and every
turn is logged to logs/events.jsonl so anyone can verify what it did.

Session 1: conversation + read-only tools. Session 2: memory across restarts (observations, preferences and proposals
kept apart; decisions only from `team decide`, never from memory) and a daily job (--daily) that runs from cron with
no chat open. Break-it tests come in session 3.
Separate from Aza-Rion (~/head-agent), which this never touches.
"""
import argparse
import datetime
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "logs", "events.jsonl")
MODEL = os.environ.get("COMPANION_MODEL", "llama3.2")
OLLAMA = "http://localhost:11434/api/chat"
DEV_USER = "kenielzep97"  # Keniel's public DEV account (read-only, public data)
MEMORY = os.path.join(HERE, "memory", "memory.jsonl")
STATE = os.path.join(HERE, "state", "dev_snapshot.json")
REPORTS = os.path.join(HERE, "reports")
CURRENT_USER_TEXT = [""]  # what Keniel said this turn, kept as evidence for preferences and proposals

SYSTEM = (
    "You are Agent One, Keniel's companion and guardian. You are new and separate from Aza-Rion. "
    "Be direct and plain. Never invent facts: if you need data, call a tool; if a tool fails, say so. "
    "You can only read. You cannot post, send, buy, delete or change anything. "
    "When you state a fact from a tool, say which tool it came from."
)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def log(event):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(event, ts=now()), ensure_ascii=False) + "\n")


# ---- tools: read-only, and the ONLY things the model can make happen -------------------------------------------
MISSION_PATH = os.path.expanduser("~/MISSION.md")


DECISIONS_PATH = os.path.expanduser("~/.team/DECISIONS.md")
PROPOSED = "PROPOSED (not approved)"
UNRECORDED = "IN KENIEL'S MISSION FILE, NO APPROVAL RECORD"
APPROVED = "APPROVED (recorded by Keniel with team decide)"


def approved_decisions():
    """Owner approvals = lines written by `team decide` (keyboard-only, hash-chained). Unchained lines don't count.
    Limit: the chain is tamper-evident, not authenticated; a process with write access could compute it."""
    import hashlib
    out, prev = [], "genesis"  # must match team decide's own seed (Aethar 737 caught "" here)
    try:
        lines = open(DECISIONS_PATH, encoding="utf-8").read().splitlines()
    except OSError:
        return out
    for line in lines:
        if line.startswith("- ") and " #chain=" in line:
            body, h = line.rsplit(" #chain=", 1)
            if hashlib.sha256((prev + "\n" + body).encode()).hexdigest()[:16] == h.strip():
                out.append({"status": APPROVED, "text": body[2:].strip()})
                prev = h.strip()
    return out


def mission_fields():
    """Every content line of ~/MISSION.md with a status parsed in code. Nothing is called approved because it lacks
    a PROPOSED mark (Kairos 2313): a line is PROPOSED if it or its section says so, otherwise UNRECORDED.
    Only `team decide` records are APPROVED (see approved_decisions)."""
    import re
    out, section_proposed = [], False
    for raw in open(MISSION_PATH, encoding="utf-8").read().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("Started:") or line.startswith("CHANGE LOG"):
            continue
        if re.match(r"^[A-Z][A-Z0-9 ()/-]+:", line):  # a new heading ends the previous section
            section_proposed = "PROPOSED" in line.split(":", 1)[0] or "are PROPOSED" in line
        m = re.match(r"^([A-Z][A-Z0-9 ]+?)(\s*\(([^)]*)\))?:\s*(.*)$", line)
        field = m.group(1).strip() if m else "item"
        text = m.group(4).strip() if m else line.lstrip("- ").strip()
        proposed = section_proposed or "PROPOSED" in line
        out.append({"field": field, "status": PROPOSED if proposed else UNRECORDED, "text": text})
    return out


def tool_read_mission(_args):
    """Keniel's owner-controlled mission file, with each key line's approval status parsed by code."""
    return json.dumps({"mission_file": mission_fields(), "approved_by_keniel": approved_decisions()}, ensure_ascii=False)


DEV_URL = f"https://dev.to/api/articles?username={DEV_USER}&per_page=10"


def tool_dev_articles(_args):
    """Keniel's 10 latest public DEV articles (not the whole account) with comment and reaction counts."""
    req = urllib.request.Request(DEV_URL,
                                 headers={"User-Agent": "agent-one-companion"})
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.load(r)
    return json.dumps([{"title": a["title"], "published": a.get("published_at"), "url": a["url"],
                        "comments": a.get("comments_count"), "reactions": a.get("public_reactions_count")}
                       for a in items], ensure_ascii=False)


# ---- memory: its own file only; remembering never grants a tool or an approval --------------------------------
MEMORY_KINDS = {"observation", "preference", "proposal"}  # "decision" is deliberately absent
MODEL_KINDS = {"observation"}  # the model may only save tool-backed observations; Keniel's statements come via /remember


def load_memory():
    try:
        return [json.loads(l) for l in open(MEMORY, encoding="utf-8") if l.strip()]
    except OSError:
        return []


def add_memory(kind, text, source, evidence):
    os.makedirs(os.path.dirname(MEMORY), exist_ok=True)
    entry = {"id": f"m-{now()}-{len(load_memory())}", "kind": kind, "text": text, "source": source,
             "evidence": evidence, "at": now()}
    with open(MEMORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log({"type": "memory_saved", "id": entry["id"], "kind": kind, "text": text, "source": source})  # every save logged
    return entry


def tool_remember(args):
    """Save one memory. Kinds are checked in code: a 'decision' can never be saved (only team decide makes one);
    an 'observation' needs a tool receipt from this same turn; preferences and proposals keep Keniel's words."""
    kind = str(args.get("kind", "")).strip().lower()
    text = str(args.get("text", "")).strip()
    if kind not in MEMORY_KINDS:
        log({"type": "memory_refused", "kind": kind, "text": text, "reason": "kind not allowed"})
        return (f"REFUSED: '{kind}' cannot be remembered. Allowed: observation, preference, proposal. "
                "Decisions exist only when Keniel records them with team decide.")
    if not text:
        return "REFUSED: nothing to remember."
    if any(m["kind"] == kind and m["text"].strip().lower() == text.lower() for m in load_memory()):
        log({"type": "memory_refused", "kind": kind, "text": text, "reason": "already remembered"})
        return f"Already remembered as {kind}; not saved twice."
    if kind in MEMORY_KINDS and kind not in MODEL_KINDS:
        log({"type": "memory_refused", "kind": kind, "text": text, "reason": "only Keniel's /remember command saves this kind"})
        return (f"REFUSED: you can't save a {kind}. Only Keniel saves preferences and proposals himself, with "
                "'/remember preference: ...' or '/remember proposal: ...'. Tell him he can do that.")
    if kind == "observation":
        tool_receipts = [u["call_id"] for u in USED if u["tool"] != "remember"]
        if not tool_receipts:
            log({"type": "memory_refused", "kind": kind, "text": text, "reason": "no tool evidence this turn"})
            return ("REFUSED: an observation needs a tool result from this turn as its source. If Keniel said this, "
                    "he can save it himself with /remember.")
        e = add_memory(kind, text, "tool receipts", tool_receipts)
    else:
        e = add_memory(kind, text, "Keniel in chat", CURRENT_USER_TEXT[0])
    log({"type": "memory_saved", "id": e["id"], "kind": kind, "text": text, "source": e["source"]})
    return f"Saved as {kind} ({e['id']})."


def forget(memory_id, reason, by="Keniel"):
    """Remove one memory by id. The removed entry is copied into the log in full, so nothing vanishes silently."""
    mem = load_memory()
    gone = [m for m in mem if m["id"] == memory_id]
    if not gone:
        return f"No memory with id {memory_id}."
    with open(MEMORY, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(m, ensure_ascii=False) + "\n" for m in mem if m["id"] != memory_id)
    log({"type": "memory_removed", "removed": gone[0], "reason": reason, "by": by})
    return f"Removed {memory_id}."


def memory_context():
    """What the model is told at start: memories with their kinds, and the only real decisions."""
    mem, dec = load_memory(), approved_decisions()
    lines = ["What you remember from before (each item keeps its kind):"]
    lines += [f"- [{m['kind']}{', LEGACY, NOT CONFIRMED by Keniel' if m.get('legacy_unverified') else ''}] {m['text']} "
              f"(source: {m['source']}, {m['at']})" for m in mem[-30:]] or ["- nothing yet"]
    lines.append("Decisions Keniel recorded with team decide (the ONLY approvals):")
    lines += [f"- {d['text']}" for d in dec] or ["- none recorded yet"]
    lines.append("Rules: a memory is not a permission. A proposal is not a decision. Say an item's kind when you use it.")
    return "\n".join(lines)


def tool_recall(_args):
    """Everything remembered, each with its kind and source, plus the only real decisions (team decide)."""
    mem = load_memory()[-30:]
    trusted = [m for m in mem if not m.get("legacy_unverified")]
    legacy = [m for m in mem if m.get("legacy_unverified")]
    return json.dumps({"memories": [{"kind": m["kind"], "text": m["text"], "source": m["source"], "at": m["at"],
                                     "keniels_words": m["evidence"] if m["source"].startswith("Keniel") else None}
                                    for m in trusted],
                       "legacy_unconfirmed": [{"kind": m["kind"], "text": m["text"], "keniels_words": m.get("evidence"),
                                               "note": "filed by the model under old rules; NOT confirmed by Keniel"}
                                              for m in legacy],
                       "decisions_recorded_by_keniel": [d["text"] for d in approved_decisions()],
                       "rule": "Anything not listed as a decision is NOT decided. If you have no record, the answer is "
                               "'unknown' or 'undecided', never yes or no. A proposal is an idea, not a decision."},
                      ensure_ascii=False)


SOURCES = {"read_mission": MISSION_PATH, "dev_articles": DEV_URL, "remember": MEMORY, "recall": MEMORY}

NO_ARGS = {"type": "object", "properties": {}, "required": []}
TOOLS = {  # the allowlist: a name not in here is blocked and logged, whatever the model asks for
    "read_mission": (tool_read_mission, "Read Keniel's mission file (what we are building and why).", NO_ARGS),
    "dev_articles": (tool_dev_articles, "List Keniel's 10 latest public DEV articles with comment and reaction counts.",
                     NO_ARGS),
    "recall": (tool_recall, "Look up what you remember from earlier conversations (preferences, proposals, "
               "observations) and any decisions Keniel recorded. Use it whenever Keniel asks what you remember.", NO_ARGS),
}  # no memory-write tool: the model cannot save anything (Kairos 2324 / Aethar 741). Observations are written by code
#    from structured tool results (the daily job); Keniel's preferences and proposals come only from /remember.
TOOL_SPECS = [{"type": "function", "function": {"name": n, "description": d, "parameters": params}}
              for n, (_, d, params) in TOOLS.items()]


USED = []  # receipts for the current turn, so the app (not the model) can name its sources


def run_tool(name, args):
    if name not in TOOLS:
        log({"type": "tool_blocked", "tool": name, "args": args, "reason": "not on the allowlist"})
        return f"BLOCKED: '{name}' is not an allowed tool."
    try:
        out = TOOLS[name][0](args)
        cid = f"{name}-{now()}"
        # receipt: the source and the exact data returned (only public DEV data and the owner's mission file)
        log({"type": "tool_call", "call_id": cid, "tool": name, "args": args, "status": "ok",
             "source": SOURCES.get(name), "result_chars": len(out), "result": out})
        USED.append({"call_id": cid, "tool": name, "source": SOURCES.get(name), "at": now()})
        return out
    except Exception as e:
        log({"type": "tool_call", "tool": name, "args": args, "status": "error", "error": f"{type(e).__name__}: {e}"})
        return f"TOOL ERROR: {type(e).__name__}: {e}"


# ---- model ------------------------------------------------------------------------------------------------------
def model(messages, tools=True):
    body = {"model": MODEL, "stream": False, "messages": messages}
    if tools:
        body["tools"] = TOOL_SPECS
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["message"]


def proposal_guard(reply):
    """If the reply repeats a PROPOSED mission item without the word 'proposed', the app appends a correction.
    Done in code because a small model drops the label (session 1 demo, 16:18:58 UTC)."""
    import re
    words = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7"}
    norm = lambda t: re.sub(r"\b(" + "|".join(words) + r")\b", lambda m: words[m.group(1).lower()], t, flags=re.I).lower()
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", reply) if x]
    notes = []
    for f in mission_fields():
        if f["status"] != PROPOSED:
            continue
        cues = [norm(c) for c in re.findall(r"\b(?:\d+|one|two|three|four|five)\s+(?:working\s+)?(?:sessions?|days?|briefs?|useful job)\b", f["text"], re.I)]
        for sent in sentences:  # per sentence: an unrelated "propose" elsewhere no longer switches the check off
            ns = norm(sent)
            if any(c in ns for c in cues) and "propos" not in ns:
                notes.append(f"[App note, not the model: this is PROPOSED, not approved by Keniel: {f['text']}]")
                break
    if notes:
        return reply + "\n" + "\n".join(dict.fromkeys(notes)), True
    return reply, False


def footer():
    """Sources named by the app from its own tool receipts, not by the model."""
    if not USED:
        return "[Sources: none; no tool was used for this answer.]"
    return "[Sources: " + "; ".join(f"{u['tool']} -> {u['source']} at {u['at']}" for u in USED) + "]"


def owner_remember(user_text):
    """Explicit owner command, handled by code: '/remember preference: ...' or '/remember proposal: ...'.
    Returns a reply string, or None if this isn't a /remember command."""
    import re
    m = re.match(r"^/remember\s+(preference|proposal)\s*:\s*(.+)$", user_text.strip(), re.I | re.S)
    if not user_text.strip().lower().startswith("/remember"):
        return None
    if not m:
        return "Use '/remember preference: ...' or '/remember proposal: ...'. Nothing saved."
    kind, text = m.group(1).lower(), m.group(2).strip()
    mem = load_memory()
    same = [x for x in mem if x["kind"] == kind and x["text"].lower() == text.lower()]
    if same and same[0].get("legacy_unverified"):  # retyping an old, unconfirmed memory confirms it (Kairos 1987)
        for x in mem:
            if x["id"] == same[0]["id"]:
                x.pop("legacy_unverified", None)
                x.update(source="Keniel's /remember command", confirmed_by_keniel=user_text.strip(), confirmed_at=now())
        with open(MEMORY, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in mem)
        log({"type": "memory_confirmed", "id": same[0]["id"], "kind": kind, "text": text, "by": "Keniel's /remember"})
        return f"Confirmed: {kind} '{text}' is now marked as yours ({same[0]['id']})."
    if same:
        return f"Already remembered as {kind}."
    e = add_memory(kind, text, "Keniel's /remember command", user_text.strip())
    log({"type": "memory_saved", "id": e["id"], "kind": kind, "text": text, "source": e["source"]})
    return f"Saved as {kind} ({e['id']}), from your own command."


def turn(history, user_text, max_steps=4):
    direct = owner_remember(user_text)
    if direct is not None:
        log({"type": "user", "text": user_text})
        log({"type": "reply", "text": direct, "model": "none (code)"})
        return direct
    USED.clear()
    CURRENT_USER_TEXT[0] = user_text
    history.append({"role": "user", "content": user_text})
    log({"type": "user", "text": user_text})
    t0 = datetime.datetime.now(datetime.timezone.utc)
    for _ in range(max_steps):
        msg = model(history)
        history.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            reply, corrected = proposal_guard(msg.get("content", "").strip())
            reply = reply + "\n" + footer()
            msg["content"] = reply  # the model's next turn sees the correction and the sources (Kairos 1982)
            secs = round((datetime.datetime.now(datetime.timezone.utc) - t0).total_seconds())
            log({"type": "reply", "text": reply, "model": MODEL, "seconds": secs, "status_correction": corrected,
                 "receipts": [u["call_id"] for u in USED]})
            return reply
        for c in calls:
            name, args = c["function"]["name"], c["function"].get("arguments") or {}
            history.append({"role": "tool", "content": run_tool(name, args)})
    reply = "I stopped after several tool steps without an answer. That is a failure, logged."
    log({"type": "reply", "text": reply, "model": MODEL, "status": "step_limit"})
    return reply


# ---- daily job: no chat; runs from cron ---------------------------------------------------------------------------
def parent_name():
    """What actually launched this process (e.g. cron or a shell), read from the OS, not assumed."""
    import subprocess
    try:
        out = subprocess.run(["ps", "-o", "comm=", "-p", str(os.getppid())], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"

def daily():
    """Check Keniel's latest DEV articles, compare with the last check, write a short report. Facts come from code;
    the model only writes the 'what deserves attention' paragraph. A failed fetch reports failure and changes nothing."""
    log({"type": "start", "mode": "daily", "pid": os.getpid(), "ppid": os.getppid(), "parent": parent_name(), "model": MODEL})
    stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")  # seconds: two runs never collide
    os.makedirs(REPORTS, exist_ok=True)
    report_path = os.path.join(REPORTS, f"{stamp}.md")
    raw = run_tool("dev_articles", {})
    if raw.startswith("TOOL ERROR"):
        open(report_path, "w").write(f"# Agent One daily check {stamp}\n\nFAILED: could not read DEV ({raw}). "
                                     "Nothing compared, nothing changed. Last snapshot kept.\n")
        log({"type": "stop", "mode": "daily", "status": "fetch_failed", "report": report_path})
        return 1
    now_items = {a["url"]: a for a in json.loads(raw)}
    try:
        prev = json.load(open(STATE, encoding="utf-8"))
    except OSError:
        prev = None
    facts, new_comments, new_articles = [], [], []
    if prev is None:
        facts.append(f"First check: baseline recorded for the latest {len(now_items)} articles. No changes to report yet.")
    else:
        for url, a in now_items.items():
            b = prev.get(url)
            if b is None:
                new_articles.append(a["title"])
                facts.append(f"NEW in the latest 10: \"{a['title']}\" ({a['comments']} comments, {a['reactions']} reactions)")
                continue
            if (a["comments"] or 0) > (b["comments"] or 0):
                new_comments.append(a["title"])
                facts.append(f"NEW COMMENTS: \"{a['title']}\" {b['comments']} -> {a['comments']} "
                             f"(+{a['comments'] - b['comments']})")
            if (a["reactions"] or 0) != (b["reactions"] or 0):
                facts.append(f"reactions: \"{a['title']}\" {b['reactions']} -> {a['reactions']}")
        for url, b in prev.items():
            if url not in now_items:
                facts.append(f"left the latest 10 (not necessarily deleted): \"{b['title']}\"")
        if not facts:
            facts.append("No changes since the last check.")
    # Evidence boundary (Kairos/Aethar, session 2 review): only the counts were retrieved, never comment text, so
    # nothing here may claim what a comment says. Attention lines are written by code, not guessed by the model.
    att = [f"- New comment count on \"{t}\". The comment text was not retrieved, so who wrote it, what it says and "
           "whether it needs anything from you are unknown." for t in new_comments]
    att += [f"- A new article appeared in your latest 10: \"{t}\"." for t in new_articles]
    attention = "\n".join(att) if att else "Nothing needs your attention from this check."
    receipt = USED[-1]["call_id"] if USED else "none"
    body = (f"# Agent One daily check {stamp}\n\n## What changed (computed by code from the DEV API)\n"
            + "\n".join(f"- {f}" for f in facts)
            + f"\n\n## What deserves your attention (written by code from the facts above; no guessing)\n{attention}"
            "\n\n## What was checked\n"
            f"- Source: {DEV_URL} (latest 10 articles, not the whole account)\n- Receipt: {receipt} in logs/events.jsonl\n"
            f"- Process: pid {os.getpid()}, started by: {parent_name()} (parent pid {os.getppid()})\n")
    open(report_path, "w").write(body)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({u: {"title": a["title"], "comments": a["comments"], "reactions": a["reactions"]}
               for u, a in now_items.items()}, open(STATE, "w"), ensure_ascii=False, indent=1)
    for f in facts:  # each computed change becomes an observation the companion can recall in chat
        if f.startswith(("NEW", "reactions", "left")):
            add_memory("observation", f, "daily check", [receipt])
    log({"type": "stop", "mode": "daily", "status": "ok", "report": report_path, "changes": len(facts)})
    return 0


def main():
    ap = argparse.ArgumentParser(description="Agent One, session 1")
    ap.add_argument("--ask", action="append", help="ask one question non-interactively (repeatable)")
    ap.add_argument("--selftest", action="store_true", help="prove an unlisted tool is refused and logged")
    ap.add_argument("--daily", action="store_true", help="run the daily DEV check and write a report (for cron)")
    ap.add_argument("--forget", metavar="ID", help="(owner) remove one memory by id; the removed text is logged")
    a = ap.parse_args()
    if a.forget:
        print(forget(a.forget, "owner request from the command line"))
        return
    if a.daily:
        sys.exit(daily())
    if a.selftest:
        log({"type": "start", "mode": "selftest", "pid": os.getpid()})
        out = run_tool("publish_post", {"title": "test"})
        ok = out.startswith("BLOCKED")
        print(f"selftest: unlisted tool 'publish_post' -> {out} | {'PASS' if ok else 'FAIL'}")
        log({"type": "stop", "mode": "selftest", "pass": ok})
        sys.exit(0 if ok else 1)
    history = [{"role": "system", "content": SYSTEM + "\n\n" + memory_context()}]
    log({"type": "start", "model": MODEL, "pid": os.getpid(), "tools": sorted(TOOLS)})
    if a.ask:
        for q in a.ask:
            print(f"Keniel: {q}\nAgent One: {turn(history, q)}\n")
        log({"type": "stop", "mode": "ask"})
        return
    print("Agent One (local model, read-only). Type 'quit' to exit.")
    while True:
        try:
            q = input("Keniel: ").strip()
        except EOFError:
            break
        if q.lower() in ("quit", "exit"):
            break
        if q:
            print(f"Agent One: {turn(history, q)}\n")
    log({"type": "stop"})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log({"type": "stop", "status": "crash", "error": f"{type(e).__name__}: {e}"})
        raise
