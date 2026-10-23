from scripts.export_session import redact, render


def rec(kind, content, sidechain=False):
    return {"type": kind, "isSidechain": sidechain, "message": {"content": content}}


def test_render_user_assistant_and_tools():
    md = render(
        [
            rec("user", "rank the hubs"),
            rec(
                "assistant",
                [
                    {"type": "thinking", "thinking": "secret plan"},
                    {"type": "text", "text": "Ranking now."},
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "uv run pytest", "description": "Run tests"},
                    },
                ],
            ),
            rec("user", [{"type": "tool_result", "content": "5 passed"}]),
        ]
    )
    assert "rank the hubs" in md and "Ranking now." in md
    assert "Run tests" in md and "uv run pytest" in md and "5 passed" in md
    assert "secret plan" not in md


def test_render_strips_system_reminders_and_sidechains():
    md = render(
        [
            rec("user", "hello<system-reminder>internal</system-reminder>"),
            rec("assistant", [{"type": "text", "text": "side"}], sidechain=True),
        ]
    )
    assert "hello" in md and "internal" not in md and "side" not in md


def test_render_truncates_long_tool_output():
    md = render([rec("user", [{"type": "tool_result", "content": "x" * 5000}])])
    assert "x" * 5000 not in md and "truncated" in md


def test_redact_secrets():
    text = "key sk-proj-abcdefghijklmnop123 token gho_abcdefghijklmnop12345"
    assert redact(text) == "key sk-***REDACTED*** token gho_***REDACTED***"
