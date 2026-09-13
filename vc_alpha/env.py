"""Load API keys from `.env`.

SETUP.md has always told people to put their keys in `.env`. Nothing read it, so
they were silently ignored and the product behaved as though no key was set — the
worst possible failure, because it looks like the free tier not working rather
than a file not being loaded.

`override=False` throughout: a real environment variable always beats the file, so
CI secrets and `GROQ_API_KEY=... vc-alpha run` keep working as expected.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

from vc_alpha import paths

log = logging.getLogger(__name__)

_loaded = False


def load(*, force: bool = False) -> list[Path]:
    """Read the installation's `.env`, then the current directory's. Returns what it read.

    Both, in that order, because a developer working in a checkout keeps their keys
    beside the code while an installed copy keeps them in `~/.vc-alpha`. Loading the
    installation's first means a checkout `.env` can override it, which is the way
    round a developer expects.
    """
    global _loaded
    if _loaded and not force:
        return []

    read = []
    for candidate in (paths.env_file(), Path.cwd() / ".env"):
        if candidate.is_file() and candidate not in read:
            load_dotenv(candidate, override=False)
            read.append(candidate)

    _loaded = True
    if read:
        log.debug("loaded env from %s", ", ".join(str(p) for p in read))
    return read
