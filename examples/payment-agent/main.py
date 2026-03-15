"""Payment agent: Policy enforcement with approval workflows.

Run:
    pip install hiitl
    python main.py
"""

from hiitl import HIITL

# Initialize with a policy file and enforcement mode
hiitl = HIITL(
    agent_id="payment-agent",
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
)


def process_payment(amount: float, currency: str, account_id: str) -> None:
    """Simulated payment processing."""
    print(f"  Payment processed: {currency} {amount:.2f} → {account_id}")


def queue_for_review(decision) -> None:
    """Simulated approval queue."""
    print(f"  Queued for review (reason: {', '.join(decision.reason_codes)})")


def main():
    print("=== Payment Agent Demo ===\n")

    # Scenario 1: Normal payment — should be ALLOWED
    print("1. Normal payment ($250):")
    decision = hiitl.evaluate("process_payment", parameters={
        "amount": 250.00,
        "currency": "USD",
    }, target={
        "account_id": "acct_customer_001",
    })

    print(f"   Decision: {decision.decision} (reason: {decision.reason_codes})")
    if decision.allowed:
        process_payment(250.00, "USD", "acct_customer_001")

    # Scenario 2: Large payment — should REQUIRE_APPROVAL
    print("\n2. Large payment ($5,000):")
    decision = hiitl.evaluate("process_payment", parameters={
        "amount": 5000.00,
        "currency": "USD",
    }, target={
        "account_id": "acct_customer_002",
    })

    print(f"   Decision: {decision.decision} (reason: {decision.reason_codes})")
    if decision.needs_approval:
        queue_for_review(decision)

    # Scenario 3: Very large payment — should be BLOCKED
    print("\n3. Very large payment ($25,000):")
    decision = hiitl.evaluate("process_payment", parameters={
        "amount": 25000.00,
        "currency": "USD",
    }, target={
        "account_id": "acct_customer_003",
    })

    print(f"   Decision: {decision.decision} (reason: {decision.reason_codes})")
    if decision.blocked:
        print(f"  Blocked: {decision.reason_codes}")

    # Scenario 4: Small refund — should be ALLOWED
    print("\n4. Small refund ($150):")
    decision = hiitl.evaluate("issue_refund", parameters={
        "amount": 150.00,
        "currency": "USD",
        "original_transaction_id": "txn_abc123",
    })

    print(f"   Decision: {decision.decision} (reason: {decision.reason_codes})")
    if decision.allowed:
        print("  Refund processed (simulated)")

    print("\n=== Demo complete ===")
    print(f"Policy version: {decision.policy_version}")


if __name__ == "__main__":
    main()
