#!/usr/bin/env python3
"""
Carrier Failure Scenario: Demonstrates self-healing when selected carrier is unavailable
Note: For this demo, we'll simulate by making all carriers unavailable for a specific PIN
"""

import asyncio
import sys
import os

# Add agent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from main import LogisticsAgent

async def run_carrier_failure_scenario():
    """Run the carrier failure scenario"""
    agent = LogisticsAgent()
    # Use an order that might have carrier issues
    result = await agent.run_demo_scenario("Carrier Failure Scenario", "ORD003")
    return result

if __name__ == "__main__":
    result = asyncio.run(run_carrier_failure_scenario())
    print(f"Scenario completed with status: {result['final_status']}")