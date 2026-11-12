# MCP integration options

Type: research
Status: resolved
Blocked by:

## Question

How should Memex expose an MCP interface, given it runs offline on localhost? Survey the official Python MCP SDK (licence, maturity, availability on PyPI), the transports (stdio vs. Streamable HTTP) and how common clients (Claude Desktop, Claude Code, VS Code/Copilot) connect to each, whether the MCP server should run in-process with the web server or as a separate stdio process sharing a core library, and how MCP Resources vs. Tools vs. Prompts map onto a file-backed workspace.

## Research

Findings: [docs/research/mcp-integration.md](../../../docs/research/mcp-integration.md)

## Answer

Per [mcp-integration research](../../../docs/research/mcp-integration.md):
- Official `mcp` SDK v2 (MIT), `MCPServer` API.
- Transport: stdio, separate process launched by the AI client (`python -m memex.mcp --workspace <path>`); works without the web UI running. No HTTP transport for now.
- Architecture: REST handlers and MCP tools are both thin adapters over one shared core library (validation + conflict rules in one place).
- Surface: domain-level Tools (no raw file write), read-only `memex://` resource templates by stable id, a few user-invoked Prompts. Exact list: ticket 11.
