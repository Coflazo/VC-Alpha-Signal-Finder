"""The install lines the product prints at people.

Each optional extra is suggested by the code path that needs it. `uv sync` makes the
environment match the lockfile exactly, so `uv sync --extra sheets` uninstalls praw
and pytest on its way in — a user who follows two of these messages in turn ends up
with only the second one working. `--inexact` adds without removing.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_suggested_sync_adds_without_removing():
    # Every place the product tells someone what to type, not just the code and
    # the README: the same footgun in SETUP.md breaks the same install.
    candidates = list(ROOT.rglob("*.py")) + list(ROOT.rglob("*.md"))
    offenders = []
    for path in candidates:
        if ".venv" in path.parts or path.name == Path(__file__).name:
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if re.search(r"uv sync (?!--inexact)--extra", line):
                offenders.append(f"{path.relative_to(ROOT)}: {line.strip()}")
    assert not offenders, "these would uninstall other extras:\n" + "\n".join(offenders)
