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


def test_json_works_on_either_side_of_the_subcommand():
    """`vc-alpha status --json` is what the docs promise and what anyone types.

    argparse only accepts a top-level option before the subcommand, so that form
    was an "unrecognized arguments" error while the documentation said every
    command takes the flag.
    """
    from vc_alpha.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["status", "--json"]).json
    assert parser.parse_args(["--json", "status"]).json
    assert not parser.parse_args(["status"]).json


def test_db_can_also_follow_the_subcommand():
    from vc_alpha.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["status", "--db", "/tmp/x.sqlite"]).db == "/tmp/x.sqlite"
    assert parser.parse_args(["--db", "/tmp/x.sqlite", "status"]).db == "/tmp/x.sqlite"
    assert parser.parse_args(["status"]).db is None


def test_every_subcommand_accepts_the_common_flags():
    """Declared once through `parents`, so a new subcommand cannot forget them."""
    from vc_alpha.cli import COMMANDS, build_parser

    parser = build_parser()
    for name in COMMANDS:
        extra = {"report": ["fund"], "collect": ["hackernews"],
                 "forget": ["someone"]}.get(name, [])
        assert parser.parse_args([name, *extra, "--json"]).json, name
