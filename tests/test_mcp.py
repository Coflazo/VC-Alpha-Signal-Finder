"""The MCP server.

An MCP client is a third party by definition: whatever model is on the other end
receives whatever these tools return. The product's promise is that private material
never leaves the machine, so the test that matters most here is that a tool cannot
be used to extract a WhatsApp message.
"""

import asyncio

import pytest

from vc_alpha.mcp_server import PRIVATE_SOURCES, _safe_text, mcp


def call(name, args=None):
    return asyncio.run(mcp.call_tool(name, args or {}))


# --- the privacy boundary ----------------------------------------------------


@pytest.mark.parametrize("source", sorted(PRIVATE_SOURCES))
def test_private_source_text_never_crosses_the_boundary(source):
    """A tool that quietly handed chat logs to a remote model would break the
    product's central promise while looking helpful."""
    secret = "Ayse said her friend is raising a seed round at a 12m cap"
    out = _safe_text(source, secret)
    assert secret not in out
    assert "stays on this machine" in out


@pytest.mark.parametrize("source", ["hackernews", "substack", "github", "reddit"])
def test_public_source_text_passes_through(source):
    """Published material is exactly what these tools exist to surface."""
    assert "I built an invoice tool" in _safe_text(source, "I built an invoice tool")


def test_whatsapp_and_inbound_are_both_treated_as_private():
    assert PRIVATE_SOURCES == {"whatsapp", "inbound"}


def test_truncation_does_not_leak_the_tail():
    assert len(_safe_text("hackernews", "x" * 5000, limit=100)) == 100


# --- the tools ---------------------------------------------------------------


def test_every_tool_is_registered_and_documented():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names >= {"list_funds", "search_candidates", "list_founders",
                     "get_founder", "review_candidate", "acceptance_threshold",
                     "source_status", "collect"}
    for t in tools:
        assert t.description, f"{t.name} has no description for the model to read"


def test_list_funds_returns_the_configured_theses():
    result = call("list_funds")
    payload = result[1] if isinstance(result, tuple) else result
    assert payload, "an assistant needs the fund list to answer anything useful"


def test_acceptance_threshold_explains_itself_in_plain_english():
    """The answer goes to someone non-technical, via an assistant."""
    result = call("acceptance_threshold",
                  {"investments_left": 10, "months_left": 12, "deals_per_month": 5})
    payload = result[1] if isinstance(result, tuple) else result
    text = str(payload)
    assert "take anything scoring above" in text


def test_an_unknown_founder_gets_a_helpful_answer_not_an_exception():
    result = call("get_founder", {"founder_id": "does-not-exist"})
    payload = str(result[1] if isinstance(result, tuple) else result)
    assert "list_founders" in payload, "it should say how to find a real id"


def test_an_unknown_source_is_refused_readably():
    result = call("collect", {"source": "myspace", "how_many": 1})
    payload = str(result[1] if isinstance(result, tuple) else result)
    assert "source_status" in payload
