"""One place that builds JSON schemas for structured output.

There were two builders. `signals.schema()` was fixed after a live key returned 400
from strict mode; `report.research()` built its own and kept both faults, so stage 4
would have failed on its first real call. Two builders means a provider quirk gets
fixed once and missed once.

Strict mode, as implemented by OpenAI-compatible endpoints, demands two things that
are easy to forget because a schema without them looks perfectly valid:

  1. `additionalProperties: false` on **every** object, nested ones included.
  2. **Every** property listed in `required`. There is no such thing as an optional
     field under strict mode.

The second is awkward for genuinely conditional fields, like "if they are not
raising, when will they start". The answer is to require it and tell the model to
write "n/a", which the renderer already hides, rather than to drop it from
`required` and have the whole request rejected.
"""

from __future__ import annotations

from typing import Any


def strict_object(properties: dict[str, Any],
                  required: list[str] | None = None) -> dict[str, Any]:
    """A schema object that satisfies strict structured-output mode.

    `required` defaults to every property, which is what strict mode wants. Pass it
    explicitly only to assert a narrower set deliberately — and note that most
    providers will reject the result.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(required if required is not None else properties.keys()),
    }


def is_strict_valid(schema: dict[str, Any]) -> list[str]:
    """Problems that would make a provider reject this schema. Empty means fine.

    Walks nested objects, because the failure that reached production was on a
    nested property rather than the root.
    """
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}: additionalProperties must be false")
            props = set(node.get("properties", {}))
            missing = props - set(node.get("required", []))
            if missing:
                problems.append(f"{path}: not required: {sorted(missing)}")
        for key, child in (node.get("properties") or {}).items():
            walk(child, f"{path}/{key}")
        if isinstance(node.get("items"), dict):
            walk(node["items"], f"{path}/items")

    walk(schema, "")
    return problems
