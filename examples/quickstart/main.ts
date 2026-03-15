/**
 * Quickstart: Minimal hiitl integration.
 *
 * Run:
 *   npm install @hiitl/sdk
 *   npx ts-node main.ts
 */

import { HIITL } from '@hiitl/sdk';

// Zero-config: no API key, no policy file, no setup.
// Default mode is OBSERVE_ALL — every action is logged, nothing is blocked.
const hiitl = new HIITL();

async function sendEmail(to: string, subject: string): Promise<void> {
  console.log(`  Sent email to ${to}: ${subject}`);
}

async function main() {
  // Evaluate an action before executing it
  const decision = hiitl.evaluate({
    action: 'send_email',
    parameters: {
      to: 'user@example.com',
      subject: 'Your order has shipped',
    },
  });

  console.log(`Decision: ${decision.decision}`);
  console.log(`Allowed: ${decision.allowed}`);

  if (decision.allowed) {
    await sendEmail('user@example.com', 'Your order has shipped');
  }
}

main().catch(console.error);
