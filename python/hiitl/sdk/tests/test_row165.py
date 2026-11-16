"""Row 165 (HTL-22), the Python SDK: an unknown option is refused, naming it; the zero-config set loads.

R-0872: "no field is ever silently dropped". The constructor's options are keyword-only, so an option it does not
define (`orgID` for `org_id`) is a TypeError naming the key. policy_format.md's Policy Set Fields: the zero-config set
is a set like any other, scoped to the configured org and environment. Design: the HTL-22 test design,
row 165, behaviors 8 and 10.
"""

from __future__ import annotations

import pytest

from hiitl import HIITL

ORG_ID = "org_test000000000000000"


def test_an_option_the_constructor_does_not_define_is_refused_naming_it(tmp_path):
    with pytest.raises(TypeError, match="orgID"):
        HIITL(orgID=ORG_ID, audit_db_path=str(tmp_path / "audit.db"))


def test_the_zero_config_set_is_scoped_to_the_configured_org_and_environment(tmp_path):
    hiitl = HIITL(org_id=ORG_ID, environment="stage", audit_db_path=str(tmp_path / "audit.db"))
    try:
        zero = hiitl._empty_policy
        assert (zero.version, zero.scope.org_id, zero.scope.environment) == ("v0.0.0", ORG_ID, "stage")
        decision = hiitl.evaluate("send_email")
        assert (decision.decision, decision.policy_version) == ("OBSERVE", "v0.0.0")
    finally:
        hiitl.close()
