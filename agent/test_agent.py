#!/usr/bin/env python3
"""Simple test of the agent's ability to connect to MCP server"""

import asyncio
import sys
import os

# Add the agent directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_agent_connection():
    """Test that the agent can connect to the MCP server"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command="python",
        args=["main.py"],
        cwd=os.path.join(os.path.dirname(__file__), "..", "server")
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the session
                await session.initialize()
                print("✓ Agent successfully connected to MCP server")

                # List tools
                tools = await session.list_tools()
                print(f"✓ Available tools: {[t.name for t in tools.tools]}")

                # Test a simple call
                result = await session.call_tool("get_order", {"order_id": "ORD001"})
                print(f"✓ Test call successful: got order {result.content[0].text[:50]}...")

                return True

    except Exception as e:
        print(f"✗ Agent connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_agent_connection())
    sys.exit(0 if success else 1)
