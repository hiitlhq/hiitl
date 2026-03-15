"""Observe-first: See what your agents are doing before writing policies.

Run:
    pip install hiitl
    python main.py

This example shows the recommended onboarding path:
1. Drop in hiitl with zero config
2. See every action your agent attempts
3. Use the observations to write targeted policies
"""

from hiitl import HIITL

# Zero config — OBSERVE_ALL mode is the default
hiitl = HIITL()


def simulate_agent_actions():
    """Simulate a customer service agent doing its work."""

    actions = [
        {
            "action": "query_database",
            "parameters": {"query": "SELECT * FROM orders WHERE user_id = ?", "table": "orders"},
            "target": {"database": "production"},
        },
        {
            "action": "send_email",
            "parameters": {"to": "customer@example.com", "subject": "Order status update"},
        },
        {
            "action": "issue_refund",
            "parameters": {"amount": 89.99, "currency": "USD", "reason": "damaged item"},
            "target": {"order_id": "ord_12345"},
        },
        {
            "action": "modify_permissions",
            "parameters": {"user_id": "usr_456", "role": "admin"},
            "target": {"system": "internal_tools"},
        },
        {
            "action": "send_email",
            "parameters": {"to": "ceo@competitor.com", "subject": "Confidential data"},
            "target": {"type": "external"},
        },
    ]

    print("=== Observe-First Demo ===")
    print("All actions proceed (OBSERVE mode). Check what enforcement would do.\n")

    for i, act in enumerate(actions, 1):
        decision = hiitl.evaluate(
            act["action"],
            parameters=act.get("parameters", {}),
            target=act.get("target", {}),
        )

        status = "OBSERVED"
        would_be = decision.would_be or "ALLOW (no matching rule)"

        print(f"{i}. {act['action']}")
        print(f"   Allowed: {decision.allowed} (always true in OBSERVE mode)")
        print(f"   Would be: {would_be}")
        print(f"   Reason codes: {decision.reason_codes}")
        print()

    print("=== Observations ===")
    print("From these logs, you can now write targeted policies:")
    print("  - modify_permissions → REQUIRE_APPROVAL (sensitive action)")
    print("  - send_email to external → REQUIRE_APPROVAL (data exfiltration risk)")
    print("  - issue_refund > $50 → REQUIRE_APPROVAL (financial control)")
    print("  - query_database → ALLOW (read-only, low risk)")
    print()
    print("See the payment-agent example for a policy that enforces these rules.")


if __name__ == "__main__":
    simulate_agent_actions()
