"""Where this installation keeps its data, decided in one place.

Every module used to carry its own relative default — `data/candidates.sqlite`,
`config/theses` — which quietly meant "wherever the shell happened to be". That
works when the author runs it from the checkout and fails the moment anyone
installs it and runs `vc-alpha` from their home directory: no theses found, and a
fresh empty database created in whatever folder they were standing in.

The rule, in order:

1. `$VC_ALPHA_HOME` if set. An explicit answer always wins.
2. The current directory, if it looks like a checkout of this project. Keeps the
   development workflow and the existing database exactly as they were.
3. `~/.vc-alpha`. What an installed copy uses.

Paths are resolved on every call rather than cached at import, because tests and
the `--db` flags need to move the target without reloading modules.
"""

from __future__ import annotations

import os
from pathlib import Path

# The directory an installed copy uses. Under the user's home rather than a
# platform config dir: this holds a database they are the data controller for, and
# it should be somewhere they can find, back up and delete without a manual.
FALLBACK = Path.home() / ".vc-alpha"


def in_checkout(where: Path | None = None) -> bool:
    """True when `where` is a working copy of this project rather than any old folder.

    Checked by the package directory, not by `config/theses`, so a checkout whose
    theses have been moved out (which is now the default) is still recognised.
    """
    where = Path(where or Path.cwd())
    return (where / "vc_alpha" / "__init__.py").is_file()


def home() -> Path:
    if env := os.environ.get("VC_ALPHA_HOME"):
        return Path(env).expanduser()
    cwd = Path.cwd()
    return cwd if in_checkout(cwd) else FALLBACK


def data_dir() -> Path:
    return home() / "data"


def config_dir() -> Path:
    """Thesis configs. One YAML per fund."""
    return home() / "config" / "theses"


def db_path() -> Path:
    """`$VC_ALPHA_DB` still wins, because CI and the tests set it."""
    if env := os.environ.get("VC_ALPHA_DB"):
        return Path(env).expanduser()
    return data_dir() / "candidates.sqlite"


def reports_dir() -> Path:
    return data_dir() / "reports"


def whatsapp_dir() -> Path:
    return data_dir() / "whatsapp"


def inbox_dir() -> Path:
    return data_dir() / "inbound"


def env_file() -> Path:
    """Where the app writes keys the user types into the Setup screen."""
    return home() / ".env"


def credential_path() -> Path:
    """The Google service-account JSON, if the fund uses Sheets."""
    return home() / "config" / "service-account.json"


def calibration_file() -> Path:
    """Fitted stage-2 threshold and score weights, once there are labels."""
    return home() / "config" / "calibration.yaml"


def ensure() -> Path:
    """Create the tree on first run. Safe to call repeatedly."""
    for d in (data_dir(), config_dir(), reports_dir(), whatsapp_dir(), inbox_dir()):
        d.mkdir(parents=True, exist_ok=True)
    return home()
