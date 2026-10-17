#!/usr/bin/env python3
"""
Happy Path Scenario: Order processes successfully without issues
"""

import asyncio
import sys
import os

# Add agent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from main import LogisticsAgent

async def run_happy_path_scenario():
    """Run the happy path scenario"""
    agent = LogisticsAgent()
    result = await agent.run_demo_scenario("Happy Path Scenario", "ORD001")
    return result

if __name__ == "__main__":
    result = asyncio.run(run_happy_path_scenario())
    print(f"Scenario completed with status: {result['final_status']}")