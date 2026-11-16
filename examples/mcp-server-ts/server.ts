/**
 * A real MCP server with hiitl inline (TypeScript) — parity with examples/mcp-server.
 *
 * Every tool handler calls evaluate() before its effect. With the policy in ./policy.json and
 * mode RESPECT_POLICY, `delete_note` is blocked and `read_note` / `write_note` run; without a
 * policy (HIITL with no options) everything is observed and recorded.
 *
 * Run:
 *   npm install
 *   NOTES_DIR=./notes npx tsx server.ts        # an MCP server on stdio
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { HIITL } from '@hiitl/sdk';

const NOTES_DIR = path.resolve(process.env.NOTES_DIR ?? './notes');

const hiitl = new HIITL({
  agent_id: 'notes-mcp',
  policy_path: path.join(import.meta.dirname, 'policy.json'),
  mode: 'RESPECT_POLICY',
  audit_db_path: process.env.HIITL_AUDIT_DB ?? './hiitl_audit.db',
});

const server = new McpServer({ name: 'notes', version: '1.0.0' });
const note = (name: string) => path.join(NOTES_DIR, path.basename(name));
const text = (t: string) => ({ content: [{ type: 'text' as const, text: t }] });

/** One line per tool: evaluate the action, then act only if it is allowed. */
async function governed(action: string, parameters: Record<string, unknown>, effect: () => Promise<string>) {
  const decision = await hiitl.evaluate({ action, parameters });
  if (!decision.allowed) {
    return { ...text(`hiitl: ${decision.decision} (${decision.reason_codes.join(', ')})`), isError: true };
  }
  return text(await effect());
}

async function readNote({ name }: { name: string }) {
  return governed('read_note', { name }, () => fs.readFile(note(name), 'utf8'));
}

async function writeNote({ name, body }: { name: string; body: string }) {
  return governed('write_note', { name, bytes: body.length }, async () => {
    await fs.mkdir(NOTES_DIR, { recursive: true });
    await fs.writeFile(note(name), body);
    return `wrote ${name}`;
  });
}

async function deleteNote({ name }: { name: string }) {
  return governed('delete_note', { name }, async () => {
    await fs.unlink(note(name));
    return `deleted ${name}`;
  });
}

server.registerTool('read_note', { description: 'Read a note', inputSchema: { name: z.string() } }, readNote);
server.registerTool('write_note', { description: 'Write a note', inputSchema: { name: z.string(), body: z.string() } },
  writeNote);
server.registerTool('delete_note', { description: 'Delete a note', inputSchema: { name: z.string() } }, deleteNote);

await server.connect(new StdioServerTransport());
