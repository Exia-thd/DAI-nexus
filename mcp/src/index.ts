#!/usr/bin/env node
/**
 * DAI Nexus Global MCP Server
 *
 * Works across ALL projects. The server:
 * - Loads skills from the DAI Nexus skills/ directory
 * - Stores per-project state in {workspace}/.dainexus/
 * - Detects the current workspace dynamically
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { registerPrompts } from './api/prompts.js';
import { registerTools } from './api/tools.js';
import { setWorkspaceRoot } from './state/pipeline-manager.js';
import { setMcpServer } from './state/rpc-client.js';

const server = new Server(
  {
    name: 'dai-nexus-mcp-global',
    version: '1.0.0',
  },
  {
    capabilities: {
      prompts: {},
      tools: {},
    },
  },
);

// Detect and set workspace root BEFORE registering handlers
setWorkspaceRoot();
setMcpServer(server);

registerPrompts(server);
registerTools(server);

async function run() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('[DAI Nexus Global MCP] Running — workspace: ' + process.cwd());
}

run().catch((error) => {
  console.error('[DAI Nexus Global MCP] Fatal error:', error);
  process.exit(1);
});
