# Integration Examples - hiitl ECP

This guide shows how to integrate hiitl with popular agent frameworks and platforms.

**Philosophy**: hiitl is architecturally neutral. It works with any orchestration framework without requiring rewrites.

**Before you start.** Every example builds one client and calls `evaluate()` before the tool's effect. Three things hold for all of them:

- **Mode.** With no `api_key`, evaluation is local, against the file at `policy_path`. With an `api_key`, the client runs in hybrid mode: evaluation stays in-process and policies sync from your hiitl org, and the file at `policy_path` is used while nothing has synced yet. In TypeScript, an `api_key` together with a `server_url` means hosted evaluation instead.
- **Enforcing.** The default mode, `OBSERVE_ALL`, enforces nothing: a decision that is not ALLOW or SANDBOX comes back as `OBSERVE`, with the rule's decision in `would_be`. The one exception is a windowed `RATE_LIMIT` rule, which still refuses the call past its limit. The examples pass `mode="RESPECT_POLICY"` to enforce. Under it, an action no rule matches is `BLOCK` with `NO_MATCHING_RULE`, so the policy needs an ALLOW rule for each action you mean to let through.
- **TypeScript.** Options are snake_case (`api_key`, `policy_path`, `agent_id`). `evaluate()` returns `Decision | Promise<Decision>`: a Promise in hybrid and hosted mode, and in local mode when a rule asks a sync route. Await it in every mode. The TypeScript Decision has no `.ok` or `.blocked`; read `decision.allowed` and `decision.decision`.

The examples assume this `policy.yaml`:

```yaml
policy_set:
  name: "agent-tool-controls"
  version: "v1.0.0"
  description: "Controls on the agent's tools"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"
  rules:
    - name: "block-high-value-payments"
      description: "Payments over $500 are refused"
      priority: 100
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
      decision: "BLOCK"
      reason_code: "PAYMENT_TOO_HIGH"
    - name: "allow-agent-tools"
      description: "The agent's other tool calls proceed"
      priority: 10
      conditions:
        field: "action"
        operator: "in"
        value: ["process_payment", "send_email", "research_payment_methods"]
      decision: "ALLOW"
      reason_code: "TOOL_ALLOWED"
```

---

## Table of Contents

1. [LangChain (Python)](#langchain-python)
2. [LangChain.js (TypeScript)](#langchainjs-typescript)
3. [OpenAI Agents SDK (Python)](#openai-agents-sdk-python)
4. [Vercel AI SDK (TypeScript)](#vercel-ai-sdk-typescript)
5. [CrewAI (Python)](#crewai-python)
6. [AutoGen (Python)](#autogen-python)
7. [Custom Agent Loop (Python)](#custom-agent-loop-python)
8. [Custom Agent Loop (TypeScript)](#custom-agent-loop-typescript)
9. [Generic HTTP API](#generic-http-api)

---

## LangChain (Python)

### Wrapping Tools with hiitl

```python
import os
from langchain.agents import create_openai_functions_agent, AgentExecutor
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from hiitl import HIITL

# Initialize hiitl
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
    environment="prod",
    agent_id="langchain-agent"
)

# Define a protected tool
@tool
def process_payment(account_id: str, amount: float) -> dict:
    """Process a payment for the given account."""

    # Evaluate with hiitl before executing
    decision = hiitl.evaluate(
        "process_payment",
        operation="execute",
        target={"account_id": account_id},
        parameters={"amount": amount, "currency": "usd"}
    )

    if not decision.allowed:
        return {
            "error": "Payment blocked by policy",
            "reason": decision.reason_codes,
            "decision": decision.decision
        }

    # Execute the actual payment
    result = stripe.charge(account_id, amount)
    return {"status": "success", "transaction_id": result.id}

@tool
def send_email(email: str, subject: str, body: str) -> dict:
    """Send an email to a customer."""

    decision = hiitl.evaluate(
        "send_email",
        operation="execute",
        target={"email": email},
        parameters={"subject": subject, "body": body}
    )

    if not decision.allowed:
        return {"error": "Email blocked by policy", "reason": decision.reason_codes}

    sendgrid.send(email, subject, body)
    return {"status": "sent"}

# Create agent with protected tools
tools = [process_payment, send_email]
llm = ChatOpenAI(model="gpt-4")

agent = create_openai_functions_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools)

# Run the agent
result = agent_executor.invoke({"input": "Process a $500 payment for account acct_123"})
print(result)
```

### Custom LangChain Callback Handler

```python
from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import AgentAction
from typing import Any

class HIITLCallbackHandler(BaseCallbackHandler):
    """Callback handler that evaluates tool calls with hiitl."""

    def __init__(self, hiitl: HIITL):
        self.hiitl = hiitl

    def on_agent_action(
        self,
        action: AgentAction,
        **kwargs: Any
    ) -> Any:
        """Called when agent is about to execute a tool."""

        # parameters must be a dict; LangChain passes a str for single-input tools
        tool_input = action.tool_input if isinstance(action.tool_input, dict) else {"input": action.tool_input}

        # Evaluate with hiitl
        decision = self.hiitl.evaluate(
            action.tool,
            operation="execute",
            target={},
            parameters=tool_input
        )

        if not decision.allowed:
            # Block the action
            raise ValueError(
                f"Tool execution blocked: {decision.reason_codes}"
            )

        # Allow the action to proceed
        return None

# Use the callback handler
hiitl = HIITL(...)
callback = HIITLCallbackHandler(hiitl)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    callbacks=[callback]
)
```

---

## LangChain.js (TypeScript)

### Wrapping Tools with hiitl

```typescript
import { ChatOpenAI } from "@langchain/openai";
import { DynamicStructuredTool } from "@langchain/core/tools";
import { AgentExecutor, createOpenAIFunctionsAgent } from "langchain/agents";
import { HIITL } from "@hiitl/sdk";
import { z } from "zod";

// Initialize hiitl
const hiitl = new HIITL({
  api_key: process.env.HIITL_API_KEY,
  policy_path: "./policy.yaml",
  mode: "RESPECT_POLICY",
  environment: "prod",
  agent_id: "langchain-js-agent",
});

// Define a protected tool
const processPaymentTool = new DynamicStructuredTool({
  name: "process_payment",
  description: "Process a payment for the given account",
  schema: z.object({
    accountId: z.string(),
    amount: z.number(),
  }),
  func: async ({ accountId, amount }) => {
    // Evaluate with hiitl before executing
    const decision = await hiitl.evaluate({
      action: "process_payment",
      operation: "execute",
      target: { accountId },
      parameters: { amount, currency: "usd" },
    });

    if (!decision.allowed) {
      return JSON.stringify({
        error: "Payment blocked by policy",
        reason: decision.reason_codes,
        decision: decision.decision,
      });
    }

    // Execute the actual payment
    const result = await stripe.charges.create({
      amount: amount * 100,
      currency: "usd",
      customer: accountId,
    });

    return JSON.stringify({
      status: "success",
      transactionId: result.id,
    });
  },
});

const sendEmailTool = new DynamicStructuredTool({
  name: "send_email",
  description: "Send an email to a customer",
  schema: z.object({
    email: z.string().email(),
    subject: z.string(),
    body: z.string(),
  }),
  func: async ({ email, subject, body }) => {
    const decision = await hiitl.evaluate({
      action: "send_email",
      operation: "execute",
      target: { email },
      parameters: { subject, body },
    });

    if (!decision.allowed) {
      return JSON.stringify({
        error: "Email blocked by policy",
        reason: decision.reason_codes,
      });
    }

    await sendgrid.send({ to: email, subject, text: body });
    return JSON.stringify({ status: "sent" });
  },
});

// Create agent with protected tools
const tools = [processPaymentTool, sendEmailTool];
const llm = new ChatOpenAI({ modelName: "gpt-4" });

const agent = await createOpenAIFunctionsAgent({
  llm,
  tools,
  prompt,
});

const agentExecutor = new AgentExecutor({
  agent,
  tools,
});

// Run the agent
const result = await agentExecutor.invoke({
  input: "Process a $500 payment for account acct_123",
});
console.log(result);
```

---

## OpenAI Agents SDK (Python)

### Protecting Agent Actions

```python
import os
from openai import OpenAI
from hiitl import HIITL
import json

client = OpenAI()
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
    environment="prod",
    agent_id="openai-agent"
)

# Define tools
tools = [
    {
        "type": "function",
        "function": {
            "name": "process_payment",
            "description": "Process a payment",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "amount": {"type": "number"}
                },
                "required": ["account_id", "amount"]
            }
        }
    }
]

def execute_tool(tool_name: str, arguments: dict) -> str:
    """Execute a tool call with hiitl evaluation."""

    # Evaluate with hiitl
    decision = hiitl.evaluate(
        action=tool_name,
        operation="execute",
        target={k: v for k, v in arguments.items() if k.endswith("_id")},
        parameters=arguments
    )

    if not decision.allowed:
        return json.dumps({
            "error": "Action blocked by policy",
            "reason": decision.reason_codes,
            "decision": decision.decision
        })

    # Execute the actual tool
    if tool_name == "process_payment":
        result = stripe.charge(arguments["account_id"], arguments["amount"])
        return json.dumps({"status": "success", "transaction_id": result.id})

    return json.dumps({"error": "Unknown tool"})

# Run agent
messages = [{"role": "user", "content": "Process a $500 payment for acct_123"}]

response = client.chat.completions.create(
    model="gpt-4",
    messages=messages,
    tools=tools
)

# Handle tool calls
message = response.choices[0].message
if message.tool_calls:
    for tool_call in message.tool_calls:
        tool_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        # Execute with hiitl protection
        result = execute_tool(tool_name, arguments)

        # Add tool result to messages
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result
        })
```

---

## Vercel AI SDK (TypeScript)

### Protecting Tool Calls

```typescript
import { HIITL } from "@hiitl/sdk";
import { streamText, tool } from "ai";
import { openai } from "@ai-sdk/openai";
import { z } from "zod";

const hiitl = new HIITL({
  api_key: process.env.HIITL_API_KEY,
  policy_path: "./policy.yaml",
  mode: "RESPECT_POLICY",
  environment: "prod",
  agent_id: "vercel-ai-agent",
});

export async function POST(req: Request) {
  const { messages } = await req.json();

  const result = await streamText({
    model: openai("gpt-4"),
    messages,
    tools: {
      process_payment: tool({
        description: "Process a payment",
        parameters: z.object({
          accountId: z.string(),
          amount: z.number(),
        }),
        execute: async ({ accountId, amount }) => {
          // Evaluate with hiitl before executing
          const decision = await hiitl.evaluate({
            action: "process_payment",
            operation: "execute",
            target: { accountId },
            parameters: { amount, currency: "usd" },
          });

          if (!decision.allowed) {
            throw new Error(
              `Payment blocked: ${decision.reason_codes.join(", ")}`
            );
          }

          // Execute the actual payment
          const charge = await stripe.charges.create({
            amount: amount * 100,
            currency: "usd",
            customer: accountId,
          });

          return {
            status: "success",
            transactionId: charge.id,
          };
        },
      }),

      send_email: tool({
        description: "Send an email",
        parameters: z.object({
          email: z.string().email(),
          subject: z.string(),
          body: z.string(),
        }),
        execute: async ({ email, subject, body }) => {
          const decision = await hiitl.evaluate({
            action: "send_email",
            operation: "execute",
            target: { email },
            parameters: { subject, body },
          });

          if (!decision.allowed) {
            throw new Error(
              `Email blocked: ${decision.reason_codes.join(", ")}`
            );
          }

          await sendgrid.send({ to: email, subject, text: body });
          return { status: "sent" };
        },
      }),
    },
  });

  return result.toAIStreamResponse();
}
```

---

## CrewAI (Python)

### Protecting Crew Tasks

```python
import os
from crewai import Agent, Task, Crew
from hiitl import HIITL

hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
    environment="prod",
    agent_id="crewai-agent"
)

# Define a protected task executor
class HIITLTask(Task):
    """Task wrapper that evaluates with hiitl before execution."""

    def execute(self, context: str = "") -> str:
        # Evaluate with hiitl
        decision = hiitl.evaluate(
            self.description,
            operation="execute",
            target={},
            parameters={"context": context}
        )

        if not decision.allowed:
            return f"Task blocked: {decision.reason_codes}"

        # Execute the actual task
        return super().execute(context)

# Create agents with protected tasks
researcher = Agent(
    role="Researcher",
    goal="Research payment processing",
    backstory="Expert in financial systems"
)

payment_processor = Agent(
    role="Payment Processor",
    goal="Process payments safely",
    backstory="Handles financial transactions"
)

research_task = HIITLTask(
    description="research_payment_methods",
    agent=researcher
)

payment_task = HIITLTask(
    description="process_payment",
    agent=payment_processor
)

crew = Crew(
    agents=[researcher, payment_processor],
    tasks=[research_task, payment_task]
)

result = crew.kickoff()
```

---

## AutoGen (Python)

### Protecting Agent Actions

```python
import os
from autogen import AssistantAgent, UserProxyAgent, config_list_from_json
from hiitl import HIITL

hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
    environment="prod",
    agent_id="autogen-agent"
)

# Create a protected function
def process_payment(account_id: str, amount: float) -> dict:
    """Process a payment with hiitl protection."""

    decision = hiitl.evaluate(
        "process_payment",
        operation="execute",
        target={"account_id": account_id},
        parameters={"amount": amount, "currency": "usd"}
    )

    if not decision.allowed:
        return {
            "error": "Payment blocked",
            "reason": decision.reason_codes
        }

    result = stripe.charge(account_id, amount)
    return {"status": "success", "transaction_id": result.id}

# Register the function with AutoGen
config_list = config_list_from_json(env_or_file="OAI_CONFIG_LIST")

assistant = AssistantAgent(
    name="assistant",
    llm_config={"config_list": config_list}
)

user_proxy = UserProxyAgent(
    name="user_proxy",
    human_input_mode="NEVER",
    function_map={"process_payment": process_payment}
)

# Start the conversation
user_proxy.initiate_chat(
    assistant,
    message="Process a $500 payment for account acct_123"
)
```

---

## Custom Agent Loop (Python)

### Basic Agent Loop with hiitl

```python
import os
from openai import OpenAI
from hiitl import HIITL
import json

client = OpenAI()
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
    environment="prod",
    agent_id="custom-agent"
)

def agent_loop(user_input: str):
    """Custom agent loop with hiitl protection."""

    messages = [{"role": "user", "content": user_input}]

    while True:
        # Get LLM response
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages
        )

        message = response.choices[0].message
        messages.append(message)

        # Check if LLM wants to take an action
        if "ACTION:" in message.content:
            # Parse action from message
            action_line = [line for line in message.content.split("\n") if line.startswith("ACTION:")][0]
            action = json.loads(action_line.replace("ACTION:", "").strip())

            # Evaluate with hiitl
            decision = hiitl.evaluate(
                action["tool"],
                operation="execute",
                target=action.get("target", {}),
                parameters=action.get("parameters", {})
            )

            if not decision.allowed:
                # Add blocked message to conversation
                messages.append({
                    "role": "system",
                    "content": f"Action blocked: {decision.reason_codes}"
                })
                continue

            # Execute the action
            result = execute_action(action)
            messages.append({
                "role": "system",
                "content": f"Action result: {result}"
            })
        else:
            # No action, return response
            return message.content

def execute_action(action: dict):
    """Execute the actual action."""
    if action["tool"] == "process_payment":
        return stripe.charge(
            action["parameters"]["account_id"],
            action["parameters"]["amount"]
        )
    return None

# Run the agent
result = agent_loop("Process a $500 payment for acct_123")
print(result)
```

---

## Custom Agent Loop (TypeScript)

### Basic Agent Loop with hiitl

```typescript
import { HIITL } from "@hiitl/sdk";
import OpenAI from "openai";

const client = new OpenAI();
const hiitl = new HIITL({
  api_key: process.env.HIITL_API_KEY,
  policy_path: "./policy.yaml",
  mode: "RESPECT_POLICY",
  environment: "prod",
  agent_id: "custom-agent",
});

interface Action {
  tool: string;
  target?: Record<string, any>;
  parameters?: Record<string, any>;
}

async function agentLoop(userInput: string): Promise<string> {
  const messages: OpenAI.ChatCompletionMessageParam[] = [
    { role: "user", content: userInput },
  ];

  while (true) {
    // Get LLM response
    const response = await client.chat.completions.create({
      model: "gpt-4",
      messages,
    });

    const message = response.choices[0].message;
    messages.push(message);

    // Check if LLM wants to take an action
    if (message.content?.includes("ACTION:")) {
      // Parse action from message
      const actionLine = message.content
        .split("\n")
        .find((line) => line.startsWith("ACTION:"))!;
      const action: Action = JSON.parse(
        actionLine.replace("ACTION:", "").trim()
      );

      // Evaluate with hiitl
      const decision = await hiitl.evaluate({
        action: action.tool,
        operation: "execute",
        target: action.target || {},
        parameters: action.parameters || {},
      });

      if (!decision.allowed) {
        // Add blocked message to conversation
        messages.push({
          role: "system",
          content: `Action blocked: ${decision.reason_codes.join(", ")}`,
        });
        continue;
      }

      // Execute the action
      const result = await executeAction(action);
      messages.push({
        role: "system",
        content: `Action result: ${JSON.stringify(result)}`,
      });
    } else {
      // No action, return response
      return message.content || "";
    }
  }
}

async function executeAction(action: Action): Promise<any> {
  if (action.tool === "process_payment") {
    const charge = await stripe.charges.create({
      amount: action.parameters!.amount * 100,
      currency: "usd",
      customer: action.parameters!.accountId,
    });
    return { status: "success", transactionId: charge.id };
  }
  return null;
}

// Run the agent
const result = await agentLoop("Process a $500 payment for acct_123");
console.log(result);
```

---

## Generic HTTP API

### Middleware Pattern (Any Language)

```python
# Python example
import os
from flask import Flask, request, jsonify
from hiitl import HIITL
from functools import wraps

app = Flask(__name__)
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
    environment="prod",
    agent_id="api-server"
)

def hiitl_protected(tool_name: str):
    """Decorator to protect API endpoints with hiitl."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Extract request data
            data = request.get_json()

            # Evaluate with hiitl
            decision = hiitl.evaluate(
                action=tool_name,
                operation="execute",
                target={},
                parameters=data
            )

            if not decision.allowed:
                return jsonify({
                    "error": "Action blocked",
                    "reason": decision.reason_codes,
                    "decision": decision.decision
                }), 403

            # Execute the actual handler
            return f(*args, **kwargs)

        return wrapper
    return decorator

@app.route("/api/process-payment", methods=["POST"])
@hiitl_protected("process_payment")
def process_payment():
    data = request.get_json()
    result = stripe.charge(data["account_id"], data["amount"])
    return jsonify({"status": "success", "transaction_id": result.id})

@app.route("/api/send-email", methods=["POST"])
@hiitl_protected("send_email")
def send_email():
    data = request.get_json()
    sendgrid.send(data["email"], data["subject"], data["body"])
    return jsonify({"status": "sent"})
```

---

## Key Integration Principles

### 1. Wrap, Don't Rewrite

hiitl integrates at the tool/action boundary. You don't need to restructure your agent architecture.

### 2. Fail Gracefully

Always handle blocked actions gracefully. Return meaningful errors to the LLM so it can adjust.

### 3. Context is King

Provide rich context in the envelope:
- `target`: What resource is being affected
- `parameters`: What are the action details
- `sensitivity`: Flag high-risk actions
- `cost_estimate`: Help policies make cost-aware decisions

### 4. Test Locally First

Use local mode to develop and test policies before deploying to production.

### 5. Monitor Audit Trail

Review the audit log regularly to understand what actions are being allowed/blocked.

---

## Next Steps

- **Policy Examples**: See [Policy Cookbook](policy_cookbook.md) for common policy patterns
- **Production Deployment**: Set `HIITL_API_KEY` to run in hybrid mode. Evaluation stays in-process, policies sync down from your hiitl org, and the audit trail syncs up.

---

**Need help integrating with a framework not listed here?** See the runnable [examples](../../examples/) in the repository, or open an issue at [github.com/hiitlhq/hiitl](https://github.com/hiitlhq/hiitl/issues).
