"""One command for the whole product.

Before this there were five separate module entry points and a `vc-alpha` command
that only started the web app. That is a pile of scripts, not a command-line tool.

Every subcommand calls the same functions the web app does, so there is one
implementation of each behaviour. Output is readable by default and `--json`
everywhere for scripting.
"""

from __future__ import annotations

import argparse
import json as jsonlib
import sys
from pathlib import Path

# The database path is resolved by vc_alpha.paths, so an installed copy finds
# its data wherever it lives rather than wherever the shell happens to be.


def _emit(data, as_json: bool, render) -> None:
    """Print JSON for machines or the rendered form for people."""
    if as_json:
        print(jsonlib.dumps(data, indent=2, default=str))
    else:
        render(data)


# --- status ------------------------------------------------------------------


def cmd_status(args) -> int:
    from vc_alpha.app.main import LOCAL_ONLY, SOURCE_INFO
    from vc_alpha.db import connect
    from vc_alpha.llm import Router
    from vc_alpha import theses
    import os

    conn = connect(args.db)
    counts = {r["source"]: r["n"] for r in conn.execute(
        "SELECT source, COUNT(*) n FROM candidates GROUP BY source")}
    q = lambda s: conn.execute(s).fetchone()[0]

    data = {
        "candidates": q("SELECT COUNT(*) FROM candidates"),
        "scored": q("SELECT COUNT(*) FROM candidates WHERE similarity IS NOT NULL"),
        "reviewed_by_ai": q("SELECT COUNT(*) FROM candidates WHERE triage_json IS NOT NULL"),
        "reviewed_by_you": q("SELECT COUNT(*) FROM candidates WHERE reviewed = 1"),
        "funds": [t.name for t in theses.load_all()],
        "providers": [p.name for p in Router(conn).available()],
        "sources": {
            k: {"found": counts.get(k, 0),
                "connected": not v.get("needs") or bool(os.environ.get(v["needs"])),
                "local_only": k in LOCAL_ONLY}
            for k, v in SOURCE_INFO.items()},
    }

    def render(d):
        print(f"\n  {d['candidates']:>6} candidates found")
        print(f"  {d['scored']:>6} scored against your funds")
        print(f"  {d['reviewed_by_ai']:>6} reviewed by AI")
        print(f"  {d['reviewed_by_you']:>6} reviewed by you")
        print(f"\n  funds:     {', '.join(d['funds']) or 'none yet'}")
        if not d["funds"]:
            print(f"             {theses.NO_FUNDS}")
        print(f"  providers: {', '.join(d['providers']) or 'none configured'}")
        print("\n  sources:")
        for name, s in d["sources"].items():
            mark = "ok " if s["connected"] else "-- "
            local = "  (this machine only)" if s["local_only"] else ""
            print(f"    {mark}{name:<12} {s['found']:>5} found{local}")
        print()

    _emit(data, args.json, render)
    return 0


# --- pipeline stages ---------------------------------------------------------


def cmd_collect(args) -> int:
    from vc_alpha.collect import COLLECTORS, NEEDS_CONN, store
    from vc_alpha.db import connect
    from vc_alpha import frontier, theses

    if args.source not in COLLECTORS:
        print(f"'{args.source}' is not a source. Try: {', '.join(sorted(COLLECTORS))}",
              file=sys.stderr)
        return 2

    conn = connect(args.db)
    factory = COLLECTORS[args.source]
    collector = factory(conn) if args.source in NEEDS_CONN else factory()
    try:
        stats = frontier.expand(
            conn, collector, frontier.Budget(max_visits=args.n),
            on_candidates=lambda recs: store(conn, recs, theses.load_all()))
    except Exception as e:
        print(f"{args.source} could not run: {e}", file=sys.stderr)
        return 1

    _emit(stats, args.json, lambda s: print(
        f"  visited {s['visited']}, found {s['candidates']}, "
        f"{s['hits']} new, {s['discovered']} more places to watch"))
    return 0


def cmd_score(args) -> int:
    from vc_alpha.db import connect
    from vc_alpha.enrich.embed import Embedder, score_pending
    from vc_alpha import theses

    emb = Embedder()
    if not emb.available():
        print("No embedding model available. Run 'vc-alpha setup', or set "
              "GEMINI_API_KEY.", file=sys.stderr)
        return 1
    stats = score_pending(connect(args.db), emb, theses.load_all(), limit=args.limit)
    _emit(stats, args.json, lambda s: print(
        f"  scored {s['scored']}, filtered out {s.get('filtered', 0)} before scoring"))
    return 0


def cmd_run(args) -> int:
    """The full pass: triage, rank, report."""
    import subprocess
    # --db only when one was given. It defaults to None now that the path is
    # resolved by vc_alpha.paths, and passing None straight into argv is a
    # TypeError from subprocess rather than anything readable.
    argv = [sys.executable, "-m", "vc_alpha.pipeline", "--limit", str(args.limit)]
    if args.db:
        argv += ["--db", args.db]
    if args.research:
        argv.append("--research")
    if args.fund:
        argv += ["--thesis", args.fund]
    return subprocess.call(argv)


def cmd_entities(args) -> int:
    from vc_alpha.db import connect
    from vc_alpha import extract, founders, theses

    conn = connect(args.db)
    found = extract.build(conn)
    scored = founders.score_all(conn, theses.load_all())
    data = {**found, **scored}
    _emit(data, args.json, lambda d: print(
        f"  {d['mentions']} mentions from {d['candidates']} candidates, "
        f"{d['scored']} founders scored"))
    return 0


def cmd_report(args) -> int:
    from vc_alpha.db import connect
    from vc_alpha.output.report import write_csv
    from vc_alpha import score, theses

    thesis = next((t for t in theses.load_all() if t.id == args.fund), None)
    if not thesis:
        print(f"No fund '{args.fund}'. Try: "
              f"{', '.join(t.id for t in theses.load_all())}", file=sys.stderr)
        return 2

    conn = connect(args.db)
    rows = score.ranked(conn, args.fund, limit=args.limit)

    if args.to_sheet:
        from vc_alpha.output.sheets_writer import push
        result = push(conn, thesis, rows)
        _emit(result.as_dict(), args.json, lambda d: print(f"  {d['detail']}"))
        return 0 if result.configured else 1

    if args.csv:
        path = write_csv(conn, thesis, rows, Path(args.csv))
        print(f"  wrote {len(rows)} rows to {path}")
        return 0

    data = [{"score": r["score"], "title": r["title"], "url": r["source_url"],
             "source": r["source"]} for r in rows]

    def render(rs):
        if not rs:
            print("  Nothing yet. Run 'vc-alpha run' first.")
            return
        print(f"\n  {thesis.name}\n")
        for r in rs:
            print(f"  {r['score']:.3f}  {(r['title'] or r['url'])[:66]}")
        print()

    _emit(data, args.json, render)
    return 0


def cmd_calibrate(args) -> int:
    """Replace the guessed stage-2 threshold with one fitted from your reviews."""
    from vc_alpha import calibrate
    from vc_alpha.db import connect

    conn = connect(args.db)

    if args.action in ("distribution", "sample", "show", "evaluate"):
        import sys as _sys
        argv = ["calibrate", args.action]
        if args.action == "sample":
            argv += ["--n", str(args.n)]
        saved, _sys.argv = _sys.argv, argv
        try:
            calibrate.main()
        finally:
            _sys.argv = saved
        return 0

    try:
        cal = calibrate.fit(conn, prefer=args.prefer)
    except calibrate.NotEnoughLabels as e:
        print(f"\n  {e}\n")
        return 1

    data = {"threshold": cal.threshold, "floor": cal.floor, "weights": cal.weights,
            "labels": cal.n_labels, "precision": cal.precision,
            "recall": cal.recall, "caveats": cal.caveats}

    def render(d):
        print(f"\n  Fitted from {cal.n_labels} of your reviews.\n"
              f"    threshold {d['threshold']:.2f}  "
              f"(precision {d['precision']:.0%}, recall {d['recall']:.0%})\n"
              f"    weights   {d['weights']}")
        # Printed, not buried in the file. A number that cannot say when its own
        # evidence is thin is a guess wearing a measurement's clothes.
        for caveat in d["caveats"]:
            print(f"\n  ! {caveat}")
        print("\n  The next run uses these instead of the defaults.\n")

    _emit(data, args.json, render)
    return 0


# --- privacy -----------------------------------------------------------------


def cmd_forget(args) -> int:
    """Erase one person, on request. GDPR Article 17, as a command.

    The only route to this used to be opening a Python shell and importing a
    function, which PRIVACY.md actually instructed a fund to do. That is not a
    procedure anyone can follow under a 30-day statutory deadline.
    """
    from vc_alpha.db import connect, forget_author

    conn = connect(args.db)
    author = args.author.strip()

    scope = {
        "candidates": conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE author = ?", (author,)).fetchone()[0],
        "whatsapp": conn.execute(
            "SELECT COUNT(*) FROM whatsapp_messages WHERE sender = ?",
            (author,)).fetchone()[0],
    }

    if not args.yes:
        data = {"author": author, "would_delete": scope, "deleted": 0}
        _emit(data, args.json, lambda d: print(
            f"\n  {author}\n"
            f"    {d['would_delete']['candidates']:>4} candidates\n"
            f"    {d['would_delete']['whatsapp']:>4} WhatsApp messages\n"
            f"    plus their entity profile and every piece of evidence from them\n\n"
            f"  Nothing deleted. Re-run with --yes to erase.\n"))
        return 0

    deleted = forget_author(conn, author)
    data = {"author": author, "would_delete": scope, "deleted": deleted}
    _emit(data, args.json,
          lambda d: print(f"\n  Erased {author}: {d['deleted']} rows removed.\n"))
    return 0


def cmd_purge(args) -> int:
    """Run the retention job now. It also runs at the start of every other command."""
    from vc_alpha.db import RETENTION_DAYS, connect, expiring_within, purge_expired

    conn = connect(args.db)
    gone = purge_expired(conn)
    data = {"deleted": gone, "retention_days": RETENTION_DAYS,
            "expiring_within_7_days": expiring_within(conn, 7)}
    _emit(data, args.json, lambda d: print(
        f"\n  Deleted {d['deleted']} rows past their {d['retention_days']}-day "
        f"retention.\n  {d['expiring_within_7_days']} more expire within a week.\n"))
    return 0


# --- setup and serving -------------------------------------------------------


def cmd_setup(args) -> int:
    """Check the machine, install a local model, or add a fund from prose.

    The fund path exists because theses.NO_FUNDS points here. A message telling
    someone to run a command that does not take those arguments is worse than no
    message, and the app should not be the only way to create a thesis.
    """
    from vc_alpha.installer import auto_setup

    if args.name or args.prose:
        from vc_alpha import onboard, theses

        if not (args.name and args.prose):
            print("  Both --name and --prose are needed to add a fund.")
            return 1
        if len(args.prose.strip()) < 40:
            print("  Describe what you back in a sentence or two, not a phrase.")
            return 1
        try:
            path = onboard.create(args.name, args.prose)
        except FileExistsError as e:
            print(f"  {e}")
            return 1
        data = {"id": onboard.slugify(args.name), "path": str(path),
                "stage": onboard.infer_stage(args.prose)}
        _emit(data, args.json, lambda d: print(
            f"\n  Added {args.name} ({d['stage']}).\n  Edit {d['path']} to tune it, "
            f"then run `vc-alpha collect hackernews`.\n"))
        return 0

    steps = []
    for step in auto_setup(allow_download=not args.no_download):
        steps.append({"name": step.name, "ok": step.ok, "detail": step.detail})
        if not args.json:
            print(f"  {'ok ' if step.ok else '-- '}{step.detail}")
    if args.json:
        print(jsonlib.dumps(steps, indent=2))
    return 0


def cmd_serve(args) -> int:
    from vc_alpha.app.main import serve
    serve()
    return 0


def cmd_mcp(args) -> int:
    from vc_alpha.mcp_server import main as mcp_main
    mcp_main()
    return 0


# --- wiring ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vc-alpha",
        description="Find early-stage startups before everyone else does. "
                    "Runs entirely on this machine.")
    # --json and --db are declared twice on purpose: once on the top-level parser
    # and once on every subcommand, through `parents`. argparse only accepts a
    # top-level option *before* the subcommand, so `vc-alpha status --json` — which
    # is what the docs promise and what anyone would actually type — was an
    # "unrecognized arguments" error. Both placements work now.
    # SUPPRESS, not a default: the subparser writes into the same namespace as the
    # top-level parser, so a default of False here would overwrite a --json given
    # before the subcommand. With SUPPRESS the attribute is only set when the flag
    # is actually passed, and whichever position it appears in wins.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")

    p.add_argument("--db", default=None, help=argparse.SUPPRESS)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="command")

    def subcommand(name: str, **kw) -> argparse.ArgumentParser:
        """Every subcommand takes --json and --db, which is what the docs claim."""
        return sub.add_parser(name, parents=[common], **kw)

    subcommand("serve", help="open the app in a browser (default)")
    subcommand("status", help="what is configured and what has been found")

    c = subcommand("collect", help="look for new candidates")
    c.add_argument("source", help="hackernews, substack, github, reddit, whatsapp, inbound, linkedin")
    c.add_argument("-n", type=int, default=10, help="how many places to check")

    s = subcommand("score", help="match what was found against your funds")
    s.add_argument("--limit", type=int, default=None)

    r = subcommand("run", help="review, rank and report (stages 3 to 5)")
    r.add_argument("--limit", type=int, default=25)
    r.add_argument("--research", action="store_true", help="also research the shortlist")
    r.add_argument("--fund", help="only this fund")

    subcommand("entities", help="rebuild founder and company profiles")

    rep = subcommand("report", help="show or export a fund's report")
    rep.add_argument("fund")
    rep.add_argument("--limit", type=int, default=25)
    rep.add_argument("--csv", help="write to this file instead of printing")
    rep.add_argument("--to-sheet", action="store_true",
                     help="append new rows to the fund's Google Sheet")

    st = subcommand(
        "setup", help="check this computer, install local AI, or add a fund")
    st.add_argument("--no-download", action="store_true")
    st.add_argument("--name", help="add a fund with this name")
    st.add_argument("--prose", help="what that fund backs, in plain English")

    subcommand("mcp", help="run as an MCP server for Claude or Codex")

    f = subcommand("forget", help="erase one person, on request (GDPR)")
    f.add_argument("author", help="the name or handle exactly as stored")
    f.add_argument("--yes", action="store_true",
                   help="actually delete; without it, only report what would go")

    subcommand("purge", help="delete everything past its retention date")

    cal = subcommand(
        "calibrate", help="fit the matching threshold to your own review decisions")
    cal.add_argument("action", nargs="?", default="fit",
                     choices=["fit", "show", "distribution", "evaluate", "sample"])
    cal.add_argument("--prefer", choices=["f1", "recall"], default="recall",
                     help="recall errs toward reading a dud over missing a founder")
    cal.add_argument("--n", type=int, default=100, help="rows, for sample")
    return p


COMMANDS = {
    "serve": cmd_serve, "status": cmd_status, "collect": cmd_collect,
    "score": cmd_score, "run": cmd_run, "entities": cmd_entities,
    "report": cmd_report, "setup": cmd_setup, "mcp": cmd_mcp,
    "forget": cmd_forget, "purge": cmd_purge, "calibrate": cmd_calibrate,
}


def main() -> None:
    from vc_alpha import env, paths

    # Before anything reads os.environ to decide what is configured.
    env.load()
    paths.ensure()
    args = build_parser().parse_args()
    # No subcommand opens the app, which is what someone who typed the bare command
    # almost certainly wanted.
    sys.exit(COMMANDS[args.command or "serve"](args))


if __name__ == "__main__":
    main()
