"""Row 163(b) (HTL-22), the gateway's floor: a redaction marker is never forwarded as an argument.

The review case records the reviewer's `modified_arguments` with the org's declared fields as "[REDACTED]" (row 163(b),
ruled 2026-11-05). HTL-22 refused such a resolution; HTL-23 row 213 (ruled 2026-11-06, "the gateway fills a marked
argument from the call it holds") turned it: a marked path takes the call's own value. The floor stands either way: no
argument the upstream receives holds the marker, at any depth. This is the row's test design cell 7, restated as
row 213's behavior 3.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

import pytest

from hiitl.core.redaction import MARKER
from hiitl.mcp_proxy.tests.test_proxy_integration import _FakeDecision
from hiitl.mcp_proxy.tests.test_review_flow import _drive_proxy_with_review_backend, _MockReviewBackend

CALL = {"account_number": "GB29NWBK60161331926819", "amount": 1250,
        "lines": [{"invoice": "INV-7", "card": "4111 1111 1111 1111"}], "payee": {"email": "dana@example.com"}}


def _holds_the_marker(value) -> bool:
    if isinstance(value, dict):
        return any(_holds_the_marker(v) for v in value.values())
    if isinstance(value, list):
        return any(_holds_the_marker(v) for v in value)
    return value == MARKER


@pytest.mark.asyncio
@pytest.mark.parametrize("modified", [
    {**CALL, "account_number": MARKER, "amount": 600},
    {**CALL, "payee": {"email": MARKER}},
    {**CALL, "lines": [{"invoice": "INV-7", "card": MARKER}]},
    {**CALL, "iban": MARKER},
], ids=["top", "nested", "in a list", "a path the call lacks"])
async def test_a_marker_in_the_modified_arguments_is_never_forwarded(modified):
    backend, called = _MockReviewBackend(), []
    async with AsyncExitStack() as stack:
        client, _ = await _drive_proxy_with_review_backend(
            stack,
            upstreams={"payments": [{"name": "pay", "handler": lambda args: called.append(args) or "paid"}]},
            decision_factory=lambda n, a: _FakeDecision(decision="REQUIRE_APPROVAL"),
            backend=backend,
        )
        backend.resolve("rev_test_0000", status="modified", modified_arguments=modified, reason="pay half")
        await client.call_tool("pay", CALL)
    assert not [args for args in called if _holds_the_marker(args)], called
