"""Turn a fund's thesis, written in plain English, into a working config.

Editing YAML is the single largest barrier to anyone but the author using this.
A partner should be able to paste the paragraph they already use to describe their
fund and get a running system.

The generated config is a starting point that is meant to be edited, not a black
box. It is written with comments explaining every field, because a thesis the fund
cannot read is one they cannot correct — and they will need to correct it.
"""

from __future__ import annotations

import re
from pathlib import Path

from vc_alpha import paths
from vc_alpha.signals import SIGNALS

# Stage words in the order a company passes through them, so "pre-seed to Series A"
# can be read off the prose rather than asked for separately.
STAGES = ["idea", "prototype", "pre-seed", "seed", "series-a", "growth"]

# Weight presets by what the fund says it cares about. These are starting points
# drawn from the reasoning in signals.py, not measurements.
PRESETS = {
    "pre-seed": {"founder_quality": 0.40, "thesis_fit": 0.30, "is_building": 0.10,
                 "timing": 0.15, "reachable": 0.05, "too_late": 0.40},
    "seed": {"founder_quality": 0.30, "thesis_fit": 0.30, "is_building": 0.20,
             "timing": 0.15, "reachable": 0.05, "too_late": 0.35},
    "later": {"is_building": 0.35, "thesis_fit": 0.30, "founder_quality": 0.15,
              "timing": 0.15, "reachable": 0.05, "too_late": 0.20},
}


def infer_stage(prose: str) -> str:
    """Earliest stage mentioned, since that is what sets the weighting."""
    low = prose.lower()
    for stage in STAGES:
        if stage in low or stage.replace("-", " ") in low:
            return stage
    return "seed"


def preset_for(stage: str) -> dict[str, float]:
    if stage in ("idea", "prototype", "pre-seed"):
        return PRESETS["pre-seed"]
    if stage in ("series-a", "growth"):
        return PRESETS["later"]
    return PRESETS["seed"]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "fund"


def build_yaml(name: str, prose: str, founder_voice: str = "",
               exclude: list[str] | None = None,
               hard_signals: list[str] | None = None) -> str:
    """Render a thesis config, commented so the fund can edit it with confidence."""
    stage = infer_stage(prose)
    weights = preset_for(stage)
    tid = slugify(name)

    def block(text: str) -> str:
        return "\n".join("  " + line.strip() for line in text.strip().splitlines())

    if not founder_voice.strip():
        founder_voice = (
            "I am building something in this space. I hit this problem myself and "
            "decided to solve it properly. We are early, with a prototype and a few "
            "users, and I am looking for an investor who understands the space."
        )

    lines = [
        f"id: {tid}",
        f"name: {name}",
        "",
        "# What stage 2 embeds and matches against. Write it as a description of the",
        "# companies you want, in your own words, not as a list of tags.",
        "prose: >",
        block(prose),
        "",
        "# The same thesis as a founder would describe their own company. Both are",
        "# embedded and a candidate scores against the better match. Without this,",
        "# fund-language prose matches VC commentary far better than it matches a",
        "# founder writing 'I built a tool that reconciles invoices', which is",
        "# backwards for a product meant to find founders.",
        "founder_voice: >",
        block(founder_voice),
        "",
        f"stage_max: {stage}",
        "",
        "# Cheap string gates, applied before embedding. A hard exclude should never",
        "# cost an inference call.",
        "exclude:",
    ]
    for item in (exclude or ["recruitment agency", "dropshipping"]):
        lines.append(f"  - {item}")

    lines += [
        "",
        "# What keyword search cannot see. Put to the triage model explicitly,",
        "# because a model not asked about founder origin will not volunteer it.",
        "hard_signals:",
    ]
    for item in (hard_signals or [
        "Founder has relevant experience in this space before starting",
        "The product is core to the company rather than a thin wrapper",
    ]):
        lines.append(f"  - {item}")

    lines += [
        "",
        "# How this fund weights each signal. Edit these numbers to change what",
        f"# ranks highest. Nothing is retrained. Preset for {stage}.",
        "weights:",
    ]
    for sig in SIGNALS:
        lines.append(f"  {sig.key}: {weights.get(sig.key, sig.default_weight)}")

    lines += [
        "",
        "# The report you want for each candidate. Add anything your fund asks for;",
        "# every field here becomes a question the research stage must answer.",
        "report_fields:",
        '  - key: startup_name',
        '    label: "Startup name"',
        '  - key: based_in',
        '    label: "Based in"',
        '    hint: "City and country"',
        '  - key: website',
        '    label: "Website"',
        '  - key: founded_in',
        '    label: "Founded in"',
        '    hint: "Month and year"',
        '  - key: founders',
        '    label: "Founders and contact"',
        '    hint: "LinkedIn and email are sufficient"',
        '  - key: description',
        '    label: "Description"',
        '    hint: "Company, stage, product, clients, round, investors"',
        '  - key: fit',
        '    label: "Why this fits"',
        '  - key: raising_now',
        '    label: "Are they currently raising?"',
        '    type: yes_no',
        '  - key: raising_when',
        '    label: "If not, when will they start?"',
        "    only_if: 'raising_now == \"N\"'",
        '  - key: geographic_focus',
        '    label: "Geographic focus"',
        "",
    ]
    return "\n".join(lines)


def create(name: str, prose: str, founder_voice: str = "",
           exclude: list[str] | None = None, hard_signals: list[str] | None = None,
           directory: Path | str | None = None, overwrite: bool = False) -> Path:
    """Write a thesis config. Refuses to clobber an existing one unless told to."""
    directory = Path(directory) if directory is not None else paths.config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slugify(name)}.yaml"
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists; pass overwrite=True to replace")
    path.write_text(build_yaml(name, prose, founder_voice, exclude, hard_signals))
    return path
