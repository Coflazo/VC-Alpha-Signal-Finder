#!/usr/bin/env bash
# One-command install. Nothing is sent anywhere; everything runs locally.
set -euo pipefail

echo "VC Alpha Signal Finder"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required. Install it from python.org, then re-run."
  exit 1
fi

# uv if available (much faster), otherwise fall back to pipx, then pip --user.
if command -v uv >/dev/null 2>&1; then
  uv tool install --force .
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force .
else
  echo "Installing with pip. For a cleaner install, consider uv or pipx."
  python3 -m pip install --user --upgrade .
fi

cat <<'MSG'

Installed. Start it with:

    vc-alpha

It opens at http://127.0.0.1:8420 and works with no credentials configured —
collecting from Hacker News, Substack and GitHub straight away.

The Setup tab shows what each optional free key unlocks. Nothing is transmitted
to anyone: see PRIVACY.md.
MSG
