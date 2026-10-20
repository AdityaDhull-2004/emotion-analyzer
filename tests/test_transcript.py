"""The transcript converter (tools/transcript_to_html.py, spec §13, AC-15) on a small
synthetic export: turns split at "❯ ", padded message lines (blank ones too) kept with the
message even when the response follows without an empty line, the response kept line for
line in one collapsed block, HTML escaped, nothing external, earlier exports merged without
repeats, and the check against the session log."""

import json
import re
import sys

from emotion_analyzer import config

sys.path.insert(0, str(config.ROOT / "tools"))
import transcript_to_html as tt  # noqa: E402

W = 40


def _message(first, *rest):
    """A user message as the export pads it: every line, even a blank one, W wide."""
    return [("❯ " + first).ljust(W)] + [("  " + line).ljust(W) for line in rest]


EXPORT = "\n".join([
    " ▐▛███▜▌   Claude Code v9.9.9",
    "▝▜█████▛▘  Some Model · Plan",
    "",
    *_message("Build it. Use <b>bold</b> & keep", "going.", "", "Second paragraph."),
    "",
    "  Read 1 file (ctrl+o to expand)",
    "",
    "● Done: see the table.",
    "",
    "  ┌───┬───┐",
    "  │ a │ b │",
    "  └───┴───┘",
    "",
    "● Write(app/<x>.html)",
    "  ⎿  Wrote 2 lines to app/<x>.html",
    "      1 <script>alert(1)</script>",
    "",
    "✻ Cooked for 1m 2s · done 9:00 PM",
    "",
    "※ recap: building it.",
    "",
    *_message("Next one."),
    "  Ran 2 shell commands (ctrl+o to expand)",
    "",
    "● All good.",
])


def test_parse_splits_turns_and_keeps_padded_lines():
    pre, turns = tt.parse(EXPORT)
    assert "Claude Code v9.9.9" in pre[0]
    assert [t.user for t in turns] == ["Build it. Use <b>bold</b> & keep\ngoing.\n\nSecond paragraph.", "Next one."]
    assert turns[0].response[0] == "  Read 1 file (ctrl+o to expand)"
    assert "  │ a │ b │" in turns[0].response
    assert turns[0].response[-1] == "※ recap: building it."
    assert turns[1].response == ["  Ran 2 shell commands (ctrl+o to expand)", "", "● All good."]


def test_page_is_standalone_escaped_and_collapsed():
    pre, turns = tt.parse(EXPORT)
    page = tt.render(pre, turns, "T", ["transcript.md"])
    assert re.findall(r'<h2><a href="#turn-(\d+)">Turn \1</a>', page) == ["1", "2"]
    assert page.count('<details class="response">') == 2 and "<details open" not in page
    assert page.count("<script>") == 1  # the page's own; the transcript's is escaped
    assert "&lt;b&gt;bold&lt;/b&gt; &amp; keep" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert not re.search(r'(src|href)="(https?:)?//', page) and "@import" not in page
    assert 'href="#turn-2"' in page and 'id="expand"' in page and 'id="collapse"' in page
    assert "worked 1m 2s" in page
    assert '<pre class="b tool">' in page and "│ a │ b │" in page


def test_backups_merge_without_repeats():
    one, two_cut, three = tt.Turn("one", ["● 1"]), tt.Turn("two", ["● 2"]), tt.Turn("three", ["● 3"])
    two_full = tt.Turn("two", ["● 2", "  and the rest"])
    merged = tt.merge([[one, two_cut], [two_full, three]])
    assert [t.user for t in merged] == ["one", "two", "three"]
    assert merged[1].response == two_full.response
    assert len(tt.merge([[one, one]])) == 2  # a repeat within one export is a real turn


def test_check_against_the_session_log(tmp_path):
    entries = [
        {"type": "user", "message": {"content": "Build it. Use <b>bold</b> & keep going.\n\nSecond paragraph."}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "user", "isCompactSummary": True, "message": {"content": "This session is being continued"}},
        {"type": "user", "message": {"content": "<task-notification> done </task-notification>"}},
        {"type": "user", "message": {"content": [{"type": "text",
                                                  "text": '<pasted_content id="1">\nNext one.\n</pasted_content id="1">'}]}},
        {"type": "user", "message": {"content": "<command-name>/export</command-name>"}},
        {"type": "user", "message": {"content": "Convert it, please."}},
    ]
    log = tmp_path / "session.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    typed = tt.typed_messages(log)
    assert len(typed) == 3
    _, turns = tt.parse(EXPORT)
    assert tt.check(turns, typed)
    assert not tt.check(turns[::-1], typed)


def test_command_line(tmp_path):
    src = tmp_path / "transcript.md"
    src.write_text(EXPORT, encoding="utf-8")
    assert tt.main([str(src)]) == 0
    assert (tmp_path / "transcript.html").read_text(encoding="utf-8").count('<section class="turn"') == 2
