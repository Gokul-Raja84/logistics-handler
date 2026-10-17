#!/usr/bin/env python3
"""
All Carriers Fail Scenario: Demonstrates clean escalation when no carriers are available
"""

import asyncio
import sys
import os

# Add agent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from main import LogisticsAgent

async def run_all_carriers_fail_scenario():
    """Run the all carriers fail scenario"""
    # We'll use an order that likely has a destination PIN with no carrier coverage
    # Or we can modify the scenario to use a specific PIN known to have no carriers
    agent = LogisticsAgent()
    result = await agent.run_demo_scenario("All Carriers Fail Scenario", "ORD999")  # Using a high order ID unlikely to exist
    return result

if __name__ == "__main__":
    result = asyncio.run(run_all_carriers_fail_scenario())
    print(f"Scenario completed with status: {result['final_status']}")