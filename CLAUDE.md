# Working on this repo

Read `README.md` first. It has the full product plan, the architecture, every skill this project needs, and every model to download. Do not start work before reading it.

## On a fresh machine

Run `./scripts/install-skills.sh` before anything else, then restart Claude Code so the skills load. The project assumes those skills are present and will be harder to work on without them.

## Commits

Commit and push after every meaningful change, however small. The sole contributor is Coflazo. Do not add `Co-Authored-By` trailers, do not mention Claude or any AI tool in commit messages, and do not add generated-with footers to PR bodies.

## Where things live

Data, config and keys resolve through `vc_alpha/paths.py`: `$VC_ALPHA_HOME`, else
the checkout when run from one, else `~/.vc-alpha`. Never hardcode a relative path
like `data/candidates.sqlite` — that is the bug paths.py exists to prevent, and it
breaks every installed copy while looking fine in development.

The five real fund theses are worked examples in `examples/theses/`, not installed
defaults. A fresh install starts with none, and `theses.load_all()` returns an empty
list rather than raising, so every caller has to say something useful.

## Writing

Docs in this repo are written plainly, in a human voice. No marketing language, no filler, no hype. When adding to the README, match what is already there.
