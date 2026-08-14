/**
 * DAI Nexus Node MCP Server Entry Point — dai-nexus workspace
 * Points to the local dainexus-node dist.
 */

import { startMCPServer } from "../dainexus-node/dist/mcp/server.js";

startMCPServer()
  .catch((err) => {
    console.error("[DAI Nexus Node MCP] Failed to start:", err);
    process.exit(1);
  });
