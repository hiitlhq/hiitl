"""Row 216 (HTL-23): a declared field contributes its count and no mean.

Ruled 2026-11-06 as the row reads: "a declared field contributes its count and no mean, by the declaration read at
every place a value leaves" (row 163(b): "review cases, `modified_arguments` and route payloads take the
declaration"; telemetry_schema.md §4, "Full parameter payloads — Never leave the SDK"). telemetry_schema.md "Numeric
Parameter Stats": "The collector reads the store's declaration as the store applies it, the org's included." At `full`,
for an action named in `telemetry_parameter_tools`, a numeric parameter the store records as the marker sends its
count, never a mean, and the collector holds no sum for it; an undeclared one sends its mean as before (row 142).
Design: the HTL-23 test design, row 216.
"""

from unittest.mock import MagicMock, patch

from hiitl.sdk.config import SyncConfig

# A refunds agent's calls: the refund amount the org declares, and a fee it does not. Distinct values, so an
# undeclared parameter's mean is never one of them.
REFUNDS = [{"amount": 42.5, "fee": 1.25, "currency": "usd"}, {"amount": 17.0, "fee": 0.5, "currency": "eur"},
           {"amount": 99.25, "fee": 2.0, "currency": "usd"}, {"amount": 310.0, "fee": 4.75, "currency": "gbp"}]


def _client(tmp_path, **declaration):
    from hiitl import HIITL

    engine = MagicMock()
    engine.initial_sync.return_value = False
    with patch("hiitl.sdk.sync_engine.SyncEngine", return_value=engine):
        return HIITL(api_key="sk_test_row216", agent_id="refunds-agent", telemetry_level="full",
                     audit_db_path=str(tmp_path / "audit.db"),
                     sync_config=SyncConfig(cache_dir=str(tmp_path / "cache"), telemetry_parameter_tools=["refund"]),
                     **declaration)


def _numeric(hiitl, calls) -> dict:
    for params in calls:
        hiitl.evaluate("refund", parameters=params)
    (summary,) = [ts for ts in hiitl._telemetry_collector.flush()["tool_summaries"] if ts["action"] == "refund"]
    return {p["parameter_path"]: p["numeric_stats"] for p in summary["parameter_stats"] if "numeric_stats" in p}


def test_a_declared_parameter_sends_its_count_and_no_mean(tmp_path):
    """Behavior 1: the SDK's own declaration. The declared amount, its count; the undeclared fee, its count and mean."""
    hiitl = _client(tmp_path, redact_fields=["parameters.amount"])
    assert _numeric(hiitl, REFUNDS) == {"amount": {"count": 4},
                                        "fee": {"count": 4, "mean": round((1.25 + 0.5 + 2.0 + 4.75) / 4, 3)}}


def test_the_orgs_declaration_is_read_as_the_store_applies_it(tmp_path):
    """Behavior 2: the org's declaration as last pulled, joined to the SDK's (row 163(a)); a window in which a field
    became declared sends no mean for it, since its values include ones the store now records as the marker."""
    hiitl = _client(tmp_path)
    assert "mean" in _numeric(hiitl, REFUNDS)["fee"], "undeclared, at full: row 142's mean"

    pulled = {"policies": [], "version": "v1", "redaction_policy": {"manual_redact_fields": ["parameters.fee"]}}
    hiitl.evaluate("refund", parameters=REFUNDS[0])
    hiitl._sync_cache.update_policies(pulled, etag="e1")
    assert _numeric(hiitl, REFUNDS[1:])["fee"] == {"count": 4}
    assert _numeric(hiitl, REFUNDS)["fee"] == {"count": 4}


def test_a_declaration_that_lands_before_the_flush_sends_no_mean(tmp_path):
    """Behavior 2, where the value leaves: values counted while undeclared, then the org's declaration pulled before
    the flush; the flush reads the declaration as the store applies it then, so the fee sends its count only."""
    hiitl = _client(tmp_path)
    for params in REFUNDS:
        hiitl.evaluate("refund", parameters=params)
    hiitl._sync_cache.update_policies({"policies": [], "version": "v1", "redaction_policy": {
        "manual_redact_fields": ["parameters.fee"]}}, etag="e1")
    (summary,) = [ts for ts in hiitl._telemetry_collector.flush()["tool_summaries"] if ts["action"] == "refund"]
    numeric = {p["parameter_path"]: p["numeric_stats"] for p in summary["parameter_stats"] if "numeric_stats" in p}
    assert numeric["fee"] == {"count": 4}
    assert numeric["amount"] == {"count": 4, "mean": round((42.5 + 17.0 + 99.25 + 310.0) / 4, 3)}


def test_the_collector_holds_no_sum_for_a_declared_parameter(tmp_path):
    """Behavior 3, the structural guarantee (§4: "a parameter's sum exists only at `full`"): none for a declared one."""
    hiitl = _client(tmp_path, redact_fields=["parameters.amount"])
    for params in REFUNDS:
        hiitl.evaluate("refund", parameters=params)
    held = hiitl._telemetry_collector._tool_stats["refund"].numeric_params
    assert (held["amount"].sum, held["amount"].first_digest) == (None, None)
    assert held["fee"].sum is not None
