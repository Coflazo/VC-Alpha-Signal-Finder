"""Every schema the product sends must satisfy strict structured-output mode.

This exists because the same bug shipped twice. A live key returned 400 on the
triage schema; it was fixed there, and the research schema kept both faults because
it was built somewhere else entirely. The fix is one builder plus this test, so a
third builder cannot quietly reintroduce it.
"""

import pytest

import conftest
from vc_alpha import theses
from vc_alpha.schema import is_strict_valid, strict_object
from vc_alpha.signals import schema as triage_schema


def test_builder_sets_additional_properties_false():
    s = strict_object({"a": {"type": "string"}})
    assert s["additionalProperties"] is False


def test_builder_requires_every_property_by_default():
    """Strict mode has no optional fields, which is the part people forget."""
    s = strict_object({"a": {"type": "string"}, "b": {"type": "number"}})
    assert set(s["required"]) == {"a", "b"}


def test_the_triage_schema_is_strict_valid():
    assert is_strict_valid(triage_schema()) == []


def test_the_triage_schema_is_valid_in_its_nested_objects_too():
    """The failure that reached production was on a nested property, not the root."""
    nested = triage_schema()["properties"]["is_building"]
    assert nested["additionalProperties"] is False
    assert set(nested["required"]) == {"score", "quote"}


# Loaded from the examples directory rather than via load_all(), because
# parametrize runs at collection time — before the fixture that points
# VC_ALPHA_HOME at a seeded temp dir — so load_all() returns nothing here and
# the whole test silently becomes an empty parameter set.
EXAMPLES = theses.load_all(conftest.EXAMPLE_THESES)


@pytest.mark.parametrize("fund", [t.id for t in EXAMPLES])
def test_every_funds_research_schema_is_strict_valid(fund):
    """Measured before the fix: every thesis omitted raising_when from required, so
    every research call would have been rejected on its first attempt."""
    from vc_alpha.output.report import research_schema

    thesis = next(t for t in EXAMPLES if t.id == fund)
    assert is_strict_valid(research_schema(thesis)) == []


def test_conditional_fields_are_required_but_told_to_answer_na():
    from vc_alpha.output.report import research_schema

    treeo = next(t for t in theses.load_all() if t.id == "treeo")
    s = research_schema(treeo)
    assert "raising_when" in s["required"]
    assert "n/a" in s["properties"]["raising_when"]["description"]


def test_the_validator_catches_a_bad_schema():
    """Otherwise the test above proves nothing."""
    bad = {"type": "object", "properties": {"a": {"type": "string"}}, "required": []}
    assert is_strict_valid(bad)
