#!/usr/bin/env python3
"""Simple test to verify MCP server is working"""

import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_mcp_connection():
    """Test connection to MCP server"""
    server_params = StdioServerParameters(
        command="python",
        args=["main.py"],
        cwd="server"
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the session
                await session.initialize()

                # List available tools
                tools = await session.list_tools()
                print("Available tools:")
                for tool in tools.tools:
                    print(f"  - {tool.name}: {tool.description}")

                # Test get_order tool
                print("\nTesting get_order tool...")
                result = await session.call_tool("get_order", {"order_id": "ORD001"})
                print(f"Result: {result}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp_connection())