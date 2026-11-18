"""Row 213 (HTL-23): a marker in a reviewer's arguments is filled from the call.

Ruled 2026-11-06 as the row reads: "the gateway fills a marked argument from the call it holds, by that sentence" ("the
human contributes to the work"). The case records the reviewer's `modified_arguments` with the org's declared fields as
the marker (row 163(b)); the gateway holds the call whole, so a marked path the call holds takes the call's own value,
with the reviewer's other changes. A marked path the call does not hold has no value to take: that is an error naming
the path, and nothing is forwarded ("If a failure mode is ambiguous, default to blocking"). Design:
the HTL-23 test design, row 213, behaviors 1 and 2; behavior 3 is test_row163.py, restated.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

import pytest

from hiitl.core.redaction import MARKER
from hiitl.mcp_proxy.tests.test_proxy_integration import _FakeDecision
from hiitl.mcp_proxy.tests.test_review_flow import _drive_proxy_with_review_backend, _MockReviewBackend

CALL = {"account_number": "GB29NWBK60161331926819", "amount": 1250,
        "lines": [{"invoice": "INV-7", "card": "4111 1111 1111 1111"}], "payee": {"email": "dana@example.com"}}


async def _resolved(modified) -> tuple[object, list]:
    backend, called = _MockReviewBackend(), []
    async with AsyncExitStack() as stack:
        client, _ = await _drive_proxy_with_review_backend(
            stack,
            upstreams={"payments": [{"name": "pay", "handler": lambda args: called.append(args) or "paid"}]},
            decision_factory=lambda n, a: _FakeDecision(decision="REQUIRE_APPROVAL"),
            backend=backend,
        )
        backend.resolve("rev_test_0000", status="modified", modified_arguments=modified, reason="pay half")
        result = await client.call_tool("pay", CALL)
    return result, called


@pytest.mark.asyncio
@pytest.mark.parametrize("modified, forwarded", [
    ({**CALL, "account_number": MARKER, "amount": 600}, {**CALL, "amount": 600}),
    ({**CALL, "payee": {"email": MARKER, "name": "Dana Okafor"}},
     {**CALL, "payee": {"email": "dana@example.com", "name": "Dana Okafor"}}),
    ({**CALL, "lines": [{"invoice": "INV-7a", "card": MARKER}]},
     {**CALL, "lines": [{"invoice": "INV-7a", "card": "4111 1111 1111 1111"}]}),
], ids=["top", "nested", "in a list"])
async def test_a_marked_argument_is_filled_from_the_call(modified, forwarded):
    """Behavior 1: the call's own value at each marked path, with the reviewer's other changes, at any depth."""
    result, called = await _resolved(modified)
    assert not result.isError, "".join(getattr(c, "text", "") for c in result.content)
    assert called == [forwarded]


@pytest.mark.asyncio
@pytest.mark.parametrize("modified, path", [
    ({**CALL, "iban": MARKER}, "iban"),
    ({**CALL, "payee": {"email": MARKER, "phone": MARKER}}, "payee.phone"),
    ({**CALL, "lines": [*CALL["lines"], {"invoice": "INV-8", "card": MARKER}]}, "lines[1].card"),
    ({**CALL, "payee": MARKER, "amount": {"value": MARKER}}, "amount.value"),
], ids=["a key the call lacks", "nested", "a list entry the call lacks", "under a value that is no object"])
async def test_a_marker_the_call_cannot_fill_is_refused(modified, path):
    """Behavior 2: an error naming the path, and nothing is forwarded."""
    result, called = await _resolved(modified)
    message = "".join(getattr(c, "text", "") for c in result.content)
    assert result.isError and path in message, message
    assert called == [], "nothing is forwarded"
