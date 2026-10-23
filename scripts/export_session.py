"""Export a Claude Code session transcript (.jsonl) to readable markdown, secrets redacted.

Usage: python -m scripts.export_session <session.jsonl> docs/session/claude-code-session.md
"""

import json
import re
import sys
from pathlib import Path

MAX_TOOL_OUTPUT = 1500
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_SECRETS = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{10,}"), "sk-***REDACTED***"),
    (re.compile(r"\bgh[opsu]_[A-Za-z0-9]{10,}"), "gho_***REDACTED***"),
]


def redact(text: str) -> str:
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


def _clip(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT:
        return text
    return f"{text[:MAX_TOOL_OUTPUT]}\n… [truncated {len(text) - MAX_TOOL_OUTPUT} chars]"


def _tool_use(block: dict) -> str:
    args = block.get("input", {})
    title = args.get("description") or args.get("file_path") or args.get("skill") or ""
    body = args.get("command") or args.get("content") or args.get("prompt") or ""
    if not body and args:
        body = json.dumps(args, indent=2)
    return f"**🔧 {block.get('name')}** — {title}\n\n```\n{_clip(str(body))}\n```"


def _tool_result(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    text = _clip(str(content or "").strip())
    return f"<details><summary>result</summary>\n\n```\n{text}\n```\n</details>"


def _blocks(record: dict) -> list[str]:
    content = record["message"].get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    out = []
    for block in content or []:
        kind = block.get("type")
        if kind == "text":
            text = _REMINDER.sub("", block.get("text", "")).strip()
            if text.startswith("Base directory for this skill"):
                text = f"_[skill instructions loaded: {text.splitlines()[0]}]_"
            if text:
                out.append(text)
        elif kind == "tool_use":
            out.append(_tool_use(block))
        elif kind == "tool_result":
            out.append(_tool_result(block))
    return out


def render(records: list[dict]) -> str:
    parts = ["# Claude Code session transcript\n"]
    for record in records:
        if record.get("type") not in ("user", "assistant") or record.get("isSidechain"):
            continue
        blocks = _blocks(record)
        if not blocks:
            continue
        is_prompt = record["type"] == "user" and not blocks[0].startswith("<details>")
        header = (
            "## 🧑 User"
            if is_prompt
            else ("### 🤖 Claude" if record["type"] == "assistant" else "")
        )
        parts.append("\n\n".join(([header] if header else []) + blocks))
    return redact("\n\n".join(parts)) + "\n"


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    records = [json.loads(line) for line in src.read_text().splitlines() if line.strip()]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(render(records))
    print(f"wrote {dst} ({dst.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
