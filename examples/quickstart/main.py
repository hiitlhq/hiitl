"""Quickstart: Minimal hiitl integration.

Run:
    pip install hiitl
    python main.py
"""

from hiitl import HIITL

# Zero-config: no API key, no policy file, no setup.
# Default mode is OBSERVE_ALL — every action is logged, nothing is blocked.
hiitl = HIITL()


def send_email(to: str, subject: str, body: str) -> None:
    """Simulated email send."""
    print(f"  Sent email to {to}: {subject}")


def main():
    # Evaluate an action before executing it
    decision = hiitl.evaluate("send_email", parameters={
        "to": "user@example.com",
        "subject": "Your order has shipped",
        "body": "Tracking number: 1234567890",
    })

    print(f"Decision: {decision.decision}")
    print(f"Allowed: {decision.allowed}")
    print(f"Observed: {decision.observed}")

    if decision.allowed:
        send_email("user@example.com", "Your order has shipped", "...")

    # Try another action
    decision = hiitl.evaluate("delete_record", parameters={
        "table": "users",
        "record_id": "usr_789",
    })

    print(f"\nDecision: {decision.decision}")
    print(f"Allowed: {decision.allowed}")
    print(f"Would be: {decision.would_be}")

    if decision.allowed:
        print("  Record deleted (simulated)")


if __name__ == "__main__":
    main()
