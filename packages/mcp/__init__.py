"""
harness-cook MCP Server — Expose core capabilities via MCP protocol.

Model Context Protocol (MCP) lets external clients (nextX, IDEs, etc.)
discover and invoke harness-cook tools over JSON-RPC 2.0 / stdio.
"""

from __future__ import annotations

from .harness_mcp_server import HarnessMCPServer

__all__ = ["HarnessMCPServer"]