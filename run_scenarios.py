#!/usr/bin/env python3
"""
Run all demo scenarios and show a summary table
"""

import asyncio
import subprocess
import sys
import os
import json
from datetime import datetime

def run_scenario(scenario_name, script_path):
    """Run a single scenario and return results"""
    print(f"\n{'='*60}")
    print(f"Running Scenario: {scenario_name}")
    print('='*60)

    try:
        # Run the scenario script
        result = subprocess.run([
            sys.executable, script_path
        ], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))

        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)

        return {
            "name": scenario_name,
            "script": script_path,
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0
        }
    except Exception as e:
        print(f"Error running scenario: {e}")
        return {
            "name": scenario_name,
            "script": script_path,
            "return_code": -1,
            "stdout": "",
            "stderr": str(e),
            "success": False
        }

async def main():
    """Run all scenarios and show summary"""
    scenarios = [
        ("Happy Path", "scenarios/happy_path.py"),
        ("Stock Shortage", "scenarios/stock_shortage.py"),
        ("Carrier Failure", "scenarios/carrier_failure.py")
    ]

    results = []

    # First, make sure the MCP server is running in background for all scenarios
    print("Starting MCP server...")
    server_proc = subprocess.Popen([
        sys.executable, "server/main.py"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Give server time to start
    import time
    time.sleep(3)

    try:
        # Run each scenario
        for name, script in scenarios:
            result = run_scenario(name, script)
            results.append(result)

        # Print summary table
        print("\n" + "="*80)
        print("FINAL SCENARIO SUMMARY")
        print("="*80)
        print(f"{'Scenario':<20} {'Status':<10} {'Details'}")
        print("-"*80)

        for result in results:
            status = "PASS" if result["success"] else "FAIL"
            details = f"RC:{result['return_code']}"
            if not result["success"] and result["stderr"]:
                details += f" Error: {result['stderr'][:50]}..."
            print(f"{result['name']:<20} {status:<10} {details}")

    finally:
        # Clean up server process
        print("\nStopping MCP server...")
        server_proc.terminate()
        server_proc.wait()

if __name__ == "__main__":
    asyncio.run(main())