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

CONFIG_DIR = Path("config/theses")


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
    return Thesis(report_fields=fields, **raw)


def load_all(directory: Path | str = CONFIG_DIR) -> list[Thesis]:
    directory = Path(directory)
    theses = [load(p) for p in sorted(directory.glob("*.yaml"))]
    if not theses:
        raise FileNotFoundError(f"no thesis configs in {directory}")
    return theses
