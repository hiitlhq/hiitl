"""MCP server with hiitl protection.

Every tool call is evaluated against policy before execution.

Run:
    pip install hiitl mcp
    python server.py

This example shows how to add hiitl to an existing MCP server
with a single evaluate() call per tool handler.
"""

from hiitl import HIITL

# Initialize hiitl — zero config for observe mode,
# or add a policy_path for enforcement
hiitl = HIITL(
    agent_id="mcp-assistant",
    # Uncomment for enforcement:
    # policy_path="./policy.yaml",
    # mode="RESPECT_POLICY",
)


# Simulated MCP tool handlers (in a real MCP server, these would be
# registered with @server.call_tool() or server.setRequestHandler())

def handle_send_email(arguments: dict) -> dict:
    """MCP tool: send_email"""

    # One line: evaluate the action before executing
    decision = hiitl.evaluate("send_email", parameters=arguments)

    if not decision.allowed:
        return {
            "error": f"Action blocked: {decision.decision}",
            "reason_codes": decision.reason_codes,
        }

    # Action is allowed — execute it
    print(f"  Sending email to {arguments.get('to', 'unknown')}")
    return {"status": "sent", "to": arguments["to"]}


def handle_query_database(arguments: dict) -> dict:
    """MCP tool: query_database"""

    decision = hiitl.evaluate("query_database", parameters=arguments)

    if not decision.allowed:
        return {
            "error": f"Action blocked: {decision.decision}",
            "reason_codes": decision.reason_codes,
        }

    print(f"  Querying: {arguments.get('query', 'unknown')}")
    return {"status": "executed", "rows": []}


def handle_delete_record(arguments: dict) -> dict:
    """MCP tool: delete_record"""

    decision = hiitl.evaluate("delete_record", parameters=arguments,
                              sensitivity=["irreversible"])

    if decision.needs_approval:
        return {
            "status": "pending_approval",
            "message": "This action requires human approval before proceeding.",
            "reason_codes": decision.reason_codes,
        }

    if not decision.allowed:
        return {
            "error": f"Action blocked: {decision.decision}",
            "reason_codes": decision.reason_codes,
        }

    print(f"  Deleting record: {arguments.get('record_id', 'unknown')}")
    return {"status": "deleted"}


def main():
    """Simulate MCP tool calls."""
    print("=== MCP Server with hiitl Demo ===\n")

    tools = {
        "send_email": handle_send_email,
        "query_database": handle_query_database,
        "delete_record": handle_delete_record,
    }

    # Simulate tool calls from an AI agent
    calls = [
        ("send_email", {"to": "user@example.com", "subject": "Update"}),
        ("query_database", {"query": "SELECT * FROM orders", "table": "orders"}),
        ("delete_record", {"record_id": "rec_456", "table": "audit_logs"}),
    ]

    for tool_name, arguments in calls:
        print(f"Tool call: {tool_name}")
        result = tools[tool_name](arguments)
        print(f"  Result: {result}\n")


if __name__ == "__main__":
    main()
