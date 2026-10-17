#!/usr/bin/env python3
"""Extended test to verify MCP server tools are working"""

import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import json
import sys

async def test_mcp_tools():
    """Test various MCP server tools"""
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

                print("=== Testing MCP Server Tools ===\n")

                # Test 1: get_order
                print("1. Testing get_order...")
                result = await session.call_tool("get_order", {"order_id": "ORD001"})
                order_data = json.loads(result.content[0].text)
                print(f"   [PASS] Retrieved order: {order_data['order_id']} - {order_data['customer_name']}")
                print(f"       Status: {order_data['status']}, Total: ${order_data['total_amount']}\n")

                # Test 2: check_inventory (using first SKU from order)
                sku_to_test = order_data['items'][0]['sku']
                print(f"2. Testing check_inventory for SKU: {sku_to_test}...")
                result = await session.call_tool("check_inventory", {"sku": sku_to_test})
                inventory_data = json.loads(result.content[0].text)
                print(f"   [PASS] Inventory check complete")
                print(f"       Total stock across all godowns: {inventory_data['total_stock']}")
                for godown, details in inventory_data['inventory'].items():
                    print(f"         - {godown}: {details['stock']} units")
                print()

                # Test 3: list_carriers
                print("3. Testing list_carriers...")
                result = await session.call_tool("list_carriers", {"destination_pin": order_data['customer_pin']})
                carriers_data = json.loads(result.content[0].text)
                print(f"   [PASS] Found {carriers_data['count']} carriers for PIN {order_data['customer_pin']}")
                for carrier in carriers_data['available_carriers'][:2]:  # Show first 2
                    print(f"       - {carrier['name']} ({carrier['speed']}): ${carrier['cost_per_km']}/km")
                print()

                # Test 4: Reserve stock (using first godown with inventory)
                godown_id = "G001"  # Default to Chennai
                print(f"4. Testing reserve_stock from godown {godown_id}...")
                result = await session.call_tool("reserve_stock", {
                    "order_id": "ORD001", 
                    "godown_id": godown_id
                })
                reserve_data = json.loads(result.content[0].text)
                if "error" not in reserve_data:
                    print(f"   [PASS] Stock reserved successfully")
                    print(f"       Reserved {len(reserve_data['reserved_items'])} items")
                else:
                    print(f"   [FAIL] Reservation failed: {reserve_data['error']}")
                    # Try with a different godown if first fails
                    godown_id = "G002"
                    print(f"       Trying godown {godown_id} instead...")
                    result = await session.call_tool("reserve_stock", {
                        "order_id": "ORD001", 
                        "godown_id": godown_id
                    })
                    reserve_data = json.loads(result.content[0].text)
                    if "error" not in reserve_data:
                        print(f"   [PASS] Stock reserved successfully from {godown_id}")
                    else:
                        print(f"   [FAIL] Reservation also failed: {reserve_data['error']}")
                print()

                print("=== All tests completed ===")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp_tools())
