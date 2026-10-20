"""Turn a Claude Code `/export` transcript into one standalone transcript.html (spec §13,
AC-15): a "Turn N" heading for every message the user typed, the message in full under it,
and the whole response (text, commands and their output) in one collapsed block. A list of
turns and Expand all / Collapse all buttons sit at the top. All CSS and JavaScript are
inline, nothing is loaded from the internet, and the transcript's text is HTML-escaped.

    python tools/transcript_to_html.py [transcript.md] [-o transcript.html]
        [--backup transcript-backup-1.md ...] [--log SESSION.jsonl]

The export marks a user message with "❯ " in the first column. Its lines, even blank ones,
are padded with spaces to the terminal width, so it ends at the first line that isn't
padded: usually an empty line, but the response can follow directly (one turn here starts
with "Ran 2 shell commands" on the next line). Everything from there to the next "❯ " is the
response, kept line for line: the export has
already rendered Markdown for the terminal (tables are drawn with box characters), so the
page shows responses in a monospaced font with their line breaks.

If the export doesn't start at the first message (for example after a compaction), earlier
exports are merged in front: --backup files, by default transcript-backup-*.md next to the
input in number order. A turn already seen in an earlier file isn't repeated. --log checks
the turns, message by message, against what the user typed according to the session's
.jsonl log, and exits with status 1 if they don't match.
"""

import argparse
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

USER_MARK = "❯ "
LOGO = "▐▛█▜▝▘▀▙▟▌▖▗▄▞▚"
TOOL_CALL = re.compile(r"^● [A-Z][A-Za-z]*\(")  # "● Write(tasks.md)", "● Update(app/main.py)"
TIME_TAKEN = re.compile(r"^✻ \S+ for (.+?) · ")  # "✻ Cooked for 10m 14s · done 2:12 AM"
NOT_TYPED = ("<task-notification>", "<command-name>", "<command-message>", "<local-command-stdout>",
             "<local-command-caveat>", "<bash-input>", "<bash-stdout>", "<bash-stderr>", "[Request interrupted")


@dataclass
class Turn:
    user: str                                      # the message as typed: padding and indent removed
    response: list = field(default_factory=list)   # the response's lines, as exported


def parse(text):
    """(preamble lines, turns) from one export."""
    lines = text.replace("\r\n", "\n").split("\n")
    i, preamble, turns = 0, [], []
    while i < len(lines) and not lines[i].startswith(USER_MARK):
        preamble.append(lines[i])
        i += 1
    while i < len(lines):
        width = len(lines[i])
        message = [lines[i][len(USER_MARK):]]
        i += 1
        # Padded lines continue the message; ending in a space also covers wide characters.
        while i < len(lines) and lines[i] and (len(lines[i]) == width or lines[i].endswith(" ")):
            message.append(lines[i][2:] if lines[i].startswith("  ") else lines[i])
            i += 1
        response = []
        while i < len(lines) and not lines[i].startswith(USER_MARK):
            response.append(lines[i])
            i += 1
        while response and not response[0].strip():
            response.pop(0)
        while response and not response[-1].strip():
            response.pop()
        turns.append(Turn("\n".join(m.rstrip() for m in message).strip("\n"), response))
    return preamble, turns


def same_message(a, b):
    """Equal apart from whitespace: the export wraps and pads lines, the log doesn't."""
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)


def merge(sources):
    """The turns of several exports, oldest first, each turn once. A turn that an earlier
    file already has keeps the longer copy of its response (a backup taken mid-turn holds
    only part of it). Repeats within one file are real turns and are kept."""
    merged, seen = [], {}
    for turns in sources:
        added = {}
        for t in turns:
            k = re.sub(r"\s+", "", t.user)
            if k in seen:
                if len(t.response) > len(merged[seen[k]].response):
                    merged[seen[k]] = t
            else:
                added.setdefault(k, len(merged))
                merged.append(t)
        seen.update(added)
    return merged


def typed_messages(log_path):
    """What the user typed, in order, from a Claude Code session log (.jsonl): no tool
    results, compaction summaries, background-task notifications, slash commands, meta
    entries or subagent prompts. Pasted text counts; its wrapper tags are dropped."""
    out = []
    for line in open(log_path, encoding="utf-8"):
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("type") != "user" or m.get("isMeta") or m.get("isCompactSummary") or m.get("isSidechain"):
            continue
        content = m.get("message", {}).get("content")
        if isinstance(content, list):
            content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        if not isinstance(content, str):
            continue
        text = re.sub(r"</?pasted_content[^>]*>", "", content).strip()
        if text and not text.startswith(NOT_TYPED):
            out.append(text)
    return out


def check(turns, typed):
    """Each turn against the typed messages in order. Messages sent after the export (such
    as the request to convert it) are counted, not treated as missing turns."""
    matched = 0
    while matched < min(len(turns), len(typed)) and same_message(turns[matched].user, typed[matched]):
        matched += 1
    ok = matched == len(turns)
    print(f"log check: {len(turns)} turns, {len(typed)} typed messages in the log, "
          f"{matched} matched in order, {len(typed) - matched} sent after the export: {'OK' if ok else 'MISMATCH'}")
    if not ok:
        print(f"  first mismatch at turn {matched + 1}")
    return ok


def blocks(lines):
    """A response split at its first-column markers: ● (text, or a tool call with its
    output), ✻ (the time a turn took), ※ (a recap Claude Code showed between turns)."""
    out = []
    for line in lines:
        if not out or line[:1] in ("●", "✻", "※"):
            if line.startswith("●"):
                kind = "tool" if TOOL_CALL.match(line) else "say"
            else:
                kind = {"✻": "time", "※": "recap"}.get(line[:1], "say")
            out.append((kind, []))
        out[-1][1].append(line)
    return [(kind, _trim(ls)) for kind, ls in out]


def _trim(lines):
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def _pre(lines):
    rows = []
    for line in lines:
        text = html.escape(line.rstrip())
        rows.append(f'<span class="dim">{text}</span>' if line.rstrip().endswith("(ctrl+o to expand)") else text)
    return "\n".join(rows)


def _meta(preamble):
    """Claude Code's version, model and folder from the banner above the first message."""
    parts = []
    for line in preamble[:4]:
        text = " ".join(line.translate({ord(c): " " for c in LOGO}).split())
        if text:
            parts.append(text)
    return " · ".join(parts)


def render(preamble, turns, title, sources):
    toc, sections = [], []
    for n, t in enumerate(turns, 1):
        first = " ".join(t.user.split())
        toc.append(f'<li><a href="#turn-{n}"><b>Turn {n}</b> {html.escape(first[:110])}'
                   f'{"…" if len(first) > 110 else ""}</a></li>')
        parts = blocks(t.response)
        steps = sum(kind in ("say", "tool") for kind, _ in parts)
        times = [m.group(1) for kind, ls in parts if kind == "time" for m in [TIME_TAKEN.match(ls[0])] if m]
        summary = f"Claude's response · {steps} step{'s' if steps != 1 else ''}"
        if times:
            summary += " · worked " + " + ".join(times)
        body = "\n".join(f'<pre class="b {kind}">{_pre(ls)}</pre>' for kind, ls in parts) or '<p class="none">(no response)</p>'
        sections.append(f'''<section class="turn" id="turn-{n}">
<h2><a href="#turn-{n}">Turn {n}</a> <a class="top" href="#top" aria-label="Back to the list of turns">↑</a></h2>
<div class="msg">{html.escape(t.user)}</div>
<details class="response"><summary>{html.escape(summary)}</summary>
<div class="resp">
{body}
</div></details>
</section>''')
    made = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z").strip()
    sub = f"{len(turns)} turns from {html.escape(', '.join(sources))} · converted {html.escape(made)}"
    meta = html.escape(_meta(preamble))
    return PAGE.format(title=html.escape(title), meta=meta, sub=sub, toc="\n".join(toc),
                       sections="\n".join(sections))


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg: #f6f7f9; --surface: #ffffff; --text: #1d2330; --muted: #5f6b7a; --border: #d9dee6;
  --accent: #4f46e5; --user-bg: #eef0ff; --tool-bg: #f2f4f7; --recap-bg: #fff8e6; --code: #1d2330;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #12151b; --surface: #1a1f27; --text: #e6e9ef; --muted: #9aa4b2; --border: #2e3540;
    --accent: #a5b4fc; --user-bg: #232a45; --tool-bg: #20262f; --recap-bg: #2d2818; --code: #e6e9ef;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
a {{ color: var(--accent); }}
.bar {{ position: sticky; top: 0; z-index: 2; background: var(--surface); border-bottom: 1px solid var(--border);
  padding: 0.6rem 16px; display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; align-items: center; }}
.bar h1 {{ font-size: 1.1rem; margin: 0; flex: 1 1 16rem; }}
.bar button {{ font: inherit; font-size: 0.9rem; padding: 0.35rem 0.8rem; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg); color: var(--text); }}
main {{ max-width: 62rem; margin: 0 auto; padding: 1rem 16px 4rem; }}
.meta {{ color: var(--muted); font-size: 0.9rem; margin: 0.2rem 0; overflow-wrap: anywhere; }}
nav {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 0.8rem 1rem; margin: 1rem 0 2rem; }}
nav h2 {{ font-size: 1rem; margin: 0 0 0.4rem; }}
nav ol {{ list-style: none; margin: 0; padding: 0; columns: 1; }}
nav li {{ margin: 0.15rem 0; }}
nav a {{ text-decoration: none; color: var(--text); display: block; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; padding: 0.1rem 0.3rem; border-radius: 6px; }}
nav a:hover, nav a:focus {{ background: var(--user-bg); }}
nav b {{ color: var(--accent); margin-right: 0.4rem; }}
.turn {{ margin: 0 0 2rem; scroll-margin-top: 4rem; }}
.turn h2 {{ font-size: 1.25rem; margin: 0 0 0.5rem; display: flex; gap: 0.6rem; align-items: baseline; }}
.turn h2 a {{ text-decoration: none; }}
.turn h2 .top {{ font-size: 0.9rem; color: var(--muted); }}
.msg {{ white-space: pre-wrap; overflow-wrap: anywhere; background: var(--user-bg); border-left: 4px solid var(--accent);
  border-radius: 10px; padding: 0.8rem 1rem; }}
details.response {{ margin-top: 0.6rem; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }}
details.response > summary {{ cursor: pointer; padding: 0.6rem 1rem; color: var(--muted); font-size: 0.95rem; }}
details.response[open] > summary {{ border-bottom: 1px solid var(--border); }}
.resp {{ padding: 0.6rem 0.8rem; }}
pre.b {{ margin: 0 0 0.6rem; padding: 0.4rem 0.6rem; overflow-x: auto; white-space: pre; color: var(--code);
  font: 13px/1.45 ui-monospace, "Cascadia Mono", Consolas, Menlo, monospace; border-radius: 8px; }}
pre.tool {{ background: var(--tool-bg); border: 1px solid var(--border); }}
pre.time {{ color: var(--muted); }}
pre.recap {{ background: var(--recap-bg); white-space: pre-wrap; overflow-wrap: anywhere; }}
.dim {{ color: var(--muted); font-style: italic; }}
.none {{ color: var(--muted); margin: 0; }}
@media (min-width: 900px) {{ nav ol {{ columns: 2; column-gap: 2rem; }} }}
</style>
</head>
<body>
<div class="bar" id="top">
<h1>{title}</h1>
<button type="button" id="expand">Expand all</button>
<button type="button" id="collapse">Collapse all</button>
</div>
<main>
<p class="meta">{meta}</p>
<p class="meta">{sub}</p>
<nav aria-labelledby="toc-title"><h2 id="toc-title">Turns</h2><ol>
{toc}
</ol></nav>
{sections}
</main>
<script>
"use strict";
const responses = () => document.querySelectorAll("details.response");
document.getElementById("expand").addEventListener("click", () => responses().forEach((d) => {{ d.open = true; }}));
document.getElementById("collapse").addEventListener("click", () => responses().forEach((d) => {{ d.open = false; }}));
</script>
</body>
</html>
"""


def _backup_number(path):
    m = re.search(r"(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert a Claude Code /export transcript to one standalone HTML page.")
    ap.add_argument("input", nargs="?", default="transcript.md")
    ap.add_argument("-o", "--output", help="default: the input's name with .html")
    ap.add_argument("--backup", nargs="*", help="earlier exports to merge in front, oldest first "
                                                "(default: transcript-backup-*.md next to the input)")
    ap.add_argument("--log", help="the session's .jsonl log, to check the turns against what was typed")
    ap.add_argument("--title", default="Emotion Analyzer: build session transcript")
    args = ap.parse_args(argv)

    src = Path(args.input)
    backups = ([Path(p) for p in args.backup] if args.backup is not None
               else sorted(src.parent.glob("transcript-backup-*.md"), key=_backup_number))
    files = [*backups, src]
    parsed = [parse(p.read_text(encoding="utf-8-sig")) for p in files]
    turns = merge([t for _, t in parsed])
    preamble = next((pre for pre, _ in parsed if any(line.strip() for line in pre)), [])
    out = Path(args.output) if args.output else src.with_suffix(".html")
    out.write_text(render(preamble, turns, args.title, [p.name for p in files]), encoding="utf-8")
    print(f"{len(turns)} turns from {', '.join(p.name for p in files)} -> {out}")
    if args.log:
        return 0 if check(turns, typed_messages(args.log)) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
