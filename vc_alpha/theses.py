"""Thesis configs.

A thesis is two things at once: what stage 2 and 3 match against, and the report
the fund expects at the end. Keeping both in one file is deliberate. When a fund
tells you the exact fields they want (as Treeo did), that list is part of the
thesis, not a separate output concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from vc_alpha import paths


@dataclass(slots=True)
class ReportField:
    key: str
    label: str
    hint: str | None = None
    type: str | None = None
    only_if: str | None = None

    @property
    def required(self) -> bool:
        """Conditional fields are not required; everything else is."""
        return self.only_if is None


@dataclass(slots=True)
class Thesis:
    id: str
    name: str
    prose: str
    # The same thesis written as a founder would describe their own company.
    # Measured: fund-language prose matches VC newsletter copy far better than it
    # matches "I built a tool that reconciles invoices", which is backwards for a
    # product that exists to find founders. Both get embedded; best match wins.
    founder_voice: str = ""
    url: str | None = None
    stage_max: str | None = None
    cheque: list[int] = field(default_factory=list)
    must_have: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    hard_signals: list[str] = field(default_factory=list)
    # Per-signal weights. A fund tunes its own ranking by editing numbers here;
    # nothing is retrained and no other fund is affected.
    weights: dict[str, float] = field(default_factory=dict)
    report_fields: list[ReportField] = field(default_factory=list)

    def vectors_text(self) -> list[str]:
        """Everything this thesis should be matched against, one string per vector."""
        return [v for v in (self.prose, self.founder_voice) if v and v.strip()]

    def excluded(self, text: str) -> bool:
        """Cheap string gate, run before embedding.

        A hard exclude should never cost an inference call, or even an embedding.
        """
        low = text.lower()
        return any(term.lower() in low for term in self.exclude)

    def missing_must_have(self, text: str) -> list[str]:
        low = text.lower()
        return [t for t in self.must_have if t.lower() not in low]

    def report_template(self) -> str:
        """The blank report, used as the prompt scaffold for stage 4."""
        lines = [f"# {self.name} — candidate report", ""]
        for f in self.report_fields:
            lines.append(f"**{f.label}:**")
            if f.hint:
                lines.append(f"> {f.hint}")
            if f.only_if:
                lines.append(f"> (only when {f.only_if})")
            lines.append("")
        return "\n".join(lines)


def load(path: Path) -> Thesis:
    raw = yaml.safe_load(path.read_text())
    fields = [ReportField(**f) for f in raw.pop("report_fields", [])]

    # YAML types values, so a fund called 212 arrives as an integer and every
    # consumer that joins or formats names then breaks. Coerced once here rather
    # than defended against everywhere downstream.
    for key in ("id", "name"):
        if key in raw:
            raw[key] = str(raw[key])
    return Thesis(report_fields=fields, **raw)


# What every caller should say when there are no funds yet. One wording, so the
# CLI, the app and the pipeline agree on what the user is supposed to do next.
NO_FUNDS = ("No fund configured yet. Open the Setup tab and describe what you back, "
            "or run `vc-alpha setup --name 'Fund' --prose '...'`.")


def load_all(directory: Path | str | None = None) -> list[Thesis]:
    """Every fund configured on this machine, or an empty list on a fresh install.

    Empty rather than an exception: no fund yet is the ordinary state the first
    time anyone runs this, and a fresh install should show them what to do rather
    than a traceback. Callers that genuinely cannot proceed say so themselves,
    using NO_FUNDS so the wording is the same everywhere.
    """
    directory = Path(directory) if directory is not None else paths.config_dir()
    if not directory.is_dir():
        return []
    return [load(p) for p in sorted(directory.glob("*.yaml"))]
