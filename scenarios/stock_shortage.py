#!/usr/bin/env python3
"""
Stock Shortage Scenario: Demonstrates self-healing when primary godown lacks stock
"""

import asyncio
import sys
import os

# Add agent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from main import LogisticsAgent

async def run_stock_shortage_scenario():
    """Run the stock shortage scenario"""
    # Use an order that we know will trigger stock issues
    agent = LogisticsAgent()
    result = await agent.run_demo_scenario("Stock Shortage Scenario", "ORD002")
    return result

if __name__ == "__main__":
    result = asyncio.run(run_stock_shortage_scenario())
    print(f"Scenario completed with status: {result['final_status']}")