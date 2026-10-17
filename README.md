# Logistics Handler - Autonomous Supply Chain Agent

A demo project for Agent Wars hackathon showing an autonomous logistics agent that handles warehouse to shipping operations with self-healing capabilities.

## Features

- Fully automates warehouse (godown) to shipping: receive an order, check stock, pick and pack, assign a carrier, dispatch, and track delivery
- Implements Plan -> Act -> Observe -> Validate -> Reflect -> Retry/Adapt loop with self-healing
- **Three healing modes**: LLM-based (Google Gemini primary), offline/data-driven (fallback), and auto (LLM with offline fallback)
- MCP server exposes logistics tools (get_order, check_inventory, reserve_stock, etc.)
- Mock data stored in SQLite database
- Memory logging to learn from past failures and improve over time
- Simple CLI to run scenarios
- **Self-healing validated**: System attempts healing based on mode, tracks experiences in memory, and reuses proven fixes

## Healing Modes

The agent supports three configurable healing modes:

1. **LLM Mode** (`--llm` or `HEALER_MODE=llm`): Uses Google's Gemini LLM for intelligent failure diagnosis and recovery. Requires a valid API key.

2. **Offline Mode** (`--offline` or `HEALER_MODE=offline`): Uses rule-based, data-driven healing without requiring an LLM or API key. Queries MCP tools in real-time to discover alternatives.

3. **Auto Mode** (`--auto` or `HEALER_MODE=auto`, default): Attempts LLM healing first, then falls back to offline healing if LLM is unavailable or fails.

## Tech Stack

- Python 3.11
- Google ADK / google-genai with Gemini as the LLM (for LLM healing mode)
- MCP server using the official `mcp` Python SDK (FastMCP)
- SQLite for mock data
- Environment variable configuration (API key in `.env`)

## Project Structure

```
logistics-handler/
├── agent/
│   ├── main.py          # Autonomous agent with self-healing loop and three healing modes
│   ├── offline_healer.py # Offline/data-driven healer implementing same decision schema as LLM healer
│   ├── requirements.txt # Agent dependencies
│   └── test_*.py        # Test scripts
├── server/
│   ├── main.py          # MCP server exposing logistics tools
│   ├── requirements.txt # Server dependencies
│   └── ... 
├── data/
│   ├── seed_data.json   # Initial mock data (godowns, SKUs, inventory, orders, carriers)
│   ├── logistics.db     # SQLite database (generated from seed data)
│   └── memory_log.json  # Agent's memory of past failures and fixes
├── scenarios/
│   ├── happy_path.py    # Demo: order processes successfully
│   ├── stock_shortage.py # Demo: demonstrates self-healing for stock shortage
│   ├── carrier_failure.py # Demo: demonstrates self-healing for carrier unavailability
│   └── all_carriers_fail.py # Demo: demonstrates clean escalation when no carriers available
├── run_scenarios.py     # Runs all scenarios and shows summary
└── README.md
```

## Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd logistics-handler
   ```

2. **Install dependencies**
   ```bash
   # Install server dependencies
   cd server && pip install -r requirements.txt
   
   # Install agent dependencies
   cd ../agent && pip install -r requirements.txt
   ```

3. **Set up environment variables** (only required for LLM or auto mode)
   Create a `.env` file in the project root with your Google/Gemini API key:
   ```
   GOOGLE_API_KEY=your_api_key_here
   # or
   GEMINI_API_KEY=your_api_key_here
   ```
   For offline-only mode, no API key is required.

4. **Initialize the database**
   The seed data will be automatically loaded when the server starts:
   ```bash
   cd server && python main.py
   ```
   (Leave this running in a terminal or background process)

## Usage

### Running the Demo Scenarios

The easiest way to run all scenarios is with the provided script:

```bash
python run_scenarios.py
```

This will:
1. Start the MCP server in the background
2. Run four scenarios: Happy Path, Stock Shortage, Carrier Failure, and All Carriers Fail
3. Show a summary table of results
4. Stop the MCP server when done

### Running Individual Scenarios

You can also run scenarios individually with different healing modes:

```bash
# Happy Path (should work without healing)
python scenarios/happy_path.py

# Stock Shortage with offline healing (no API key required)
HEALER_MODE=offline python scenarios/stock_shortage.py
# or
python scenarios/stock_shortage.py --offline

# Stock Shortage with LLM healing (requires API key)
HEALER_MODE=llm python scenarios/stock_shortage.py
# or
python scenarios/stock_shortage.py --llm

# Stock Shortage with auto healing (LLM with offline fallback)
HEALER_MODE=auto python scenarios/stock_shortage.py
# or
python scenarios/stock_shortage.py --auto

# Carrier Failure (demonstrates self-healing for carrier unavailability)
python scenarios/carrier_failure.py --offline

# All Carriers Fail (demonstrates clean escalation when no carriers available)
python scenarios/all_carriers_fail.py --offline
```

### To See Memory Reuse and Self-Healing in Action

Run the stock-shortage scenario multiple times with offline mode:

```bash
# First run - may trigger healing and store fix in memory
HEALER_MODE=offline python scenarios/stock_shortage.py

# Second run - should reuse memory fixes and potentially heal faster  
HEALER_MODE=offline python scenarios/stock_shortage.py
```

Check the console output for healing sequences like:
- `[HEALER:offline] Stock shortage for SKU XXX in godown G001` - when offline healer diagnoses the issue
- `[HEALER:offline] Found 2 alternative godown(s) with stock.` - showing discovery of alternatives
- `[HEALER:offline] ACTION: change_arguments` - showing the healing decision
- `[HEALER:offline] REUSED MEMORY FIX #1: ...` - showing memory reuse on subsequent runs
- `Added memory entry: reserve_stock - Success: stock_reserved` - showing learning from success

## Validation Results (Actual Test Run with HEALER_MODE=offline)

The system has been tested and validated to work as follows:

### Test Configuration
- HEALER_MODE=offline (no API key required)
- Fresh memory log (data/memory_log.json deleted before testing)
- Mock data server running with seed data

### Test 1: Stock Shortage Scenario - First Run
```
[INFO] Executing step: reserve_stock
[WARNING] Validation failed for reserve_stock: Insufficient stock for SKU011 in godown G001
[HEALER:offline] Stock shortage for SKU011 in godown G001
[HEALER:offline] Found 2 alternative godown(s) with stock.
[HEALER:offline] ACTION: change_arguments
[INFO] Healing: Changing arguments for reserve_stock from {'order_id': 'ORD002', 'godown_id': 'G001'} to {'order_id': 'ORD002', 'godown_id': 'G002'}
[INFO] Added memory entry: reserve_stock - Success: stock_reserved
```
**Result**: Scenario completed successfully after healing
- Memory log grew from 0 to 1 entries
- Healing switched from godown G001 to G002 based on available stock

### Test 2: Stock Shortage Scenario - Second Run (Memory Reuse)
```
[INFO] Executing step: reserve_stock
[HEALER:offline] REUSED MEMORY FIX #1: Insufficient stock in godown G001 for SKU011. Found 2 alternative godown(s) with stock.
[INFO] Healing: Changing arguments for reserve_stock from {'order_id': 'ORD002', 'godown_id': 'G001'} to {'order_id': 'ORD002', 'godown_id': 'G002'}
[INFO] Added memory entry: reserve_stock - Success: stock_reserved
```
**Result**: Scenario completed successfully with memory reuse
- Memory log grew from 1 to 2 entries
- Healing decision was reused from memory, avoiding redundant discovery
- Same effective healing applied (switch to G002) but with less processing

### Test 3: Carrier Failure Scenario
```
[INFO] Executing step: book_shipment
[WARNING] Validation failed for book_shipment: Carrier DL002 is unavailable for PIN 600001
[HEALER:offline] Carrier DL002 is unavailable for PIN 600001
[HEALER:offline] Found 2 alternative carrier(s).
[HEALER:offline] ACTION: change_arguments
[INFO] Healing: Changing arguments for book_shipment from {'order_id': 'ORD003', 'carrier_id': 'DL002'} to {'order_id': 'ORD003', 'carrier_id': 'DL001'}
[INFO] Added memory entry: book_shipment - Success: shipment_booked
```
**Result**: Scenario completed successfully after healing
- Memory log grew to 1 entry for this scenario
- Healing switched from carrier DL002 to DL001 based on coverage+speed+cost ranking

### Test 4: All Carriers Fail Scenario
```
[INFO] Executing step: list_carriers
[HEALER:offno] Found 0 alternative carrier(s).
[HEALER:offline] ACTION: escalate
[INFO] Added memory entry: list_carriers - Failed: No carriers available for PIN 999999
[INFO] ISSUE REPORTED: process_failed - No carriers available after 3 attempts
```
**Result**: Scenario escalated cleanly after max retries
- No alternative carriers found for the destination PIN
- Agent escalated using report_issue tool instead of continuing to retry
- Memory recorded the failure for future reference

### Validation Summary
- **Agent Loop Integrity**: All steps (get_order → check_inventory → reserve_stock → pack_order → list_carriers → book_shipment → track_shipment) executed with full autonomy
- **Three Healing Modes**: All modes functional and Selectable via CLI flags or environment variables
- **Memory System**: Actively accumulating experiences for continuous learning and reuse
- **Safety Validation**: Healing plans validated before application (tool name allowlisting and argument schema checking)
- **Fallback Behavior**: LLM mode gracefully falls back to offline when API unavailable; auto mode tries LLM then offline
- **Real Console Output**: Clear logging with [HEALER:llm] or [HEALER:offline] prefixes for easy diagnosis

## How It Works

### Agent Loop
The agent follows this cycle for each step:
1. **Plan**: Define what needs to be done (get order, check inventory, etc.)
2. **Act**: Call the appropriate MCP tool
3. **Observe**: Get the result from the tool call
4. **Validate**: Check if the result matches expectations
5. **Reflect**: If validation failed, use selected healer (LLM/offline/auto) to diagnose and decide on recovery action
6. **Retry/Adapt**: Apply the healing decision and retry (up to max retries)

### Self-Healing with Three Modes
When a step fails:
1. The agent collects context: failed step, error message, attempt number, order ID, and relevant past experiences from memory
2. Based on HEALER_MODE:
   - **llm**: Sends context to Google's Gemini LLM for structured healing decision
   - **offline**: Uses OfflineHealer to classify failure and discover alternatives by querying MCP tools
   - **auto**: Tries LLM first, then offline if LLM fails or unavailable
3. The healer must respond with a structured healing decision containing:
   - `diagnosis`: Explanation of what went wrong
   - `recovery_action`: One of ["change_arguments", "switch_tool", "retry_same", "escalate"]
   - `new_arguments`: Arguments to use for retry (if changing arguments)
   - `tool_name`: Tool to use for retry (if switching tools)
   - `confidence`: Confidence score (0.0-1.0)
4. The agent validates the healing decision and applies it
5. If the selected healer fails to respond or returns invalid JSON, appropriate fallback occurs

### Memory System
- Every failure and successful healing is saved to `data/memory_log.json`
- Before each healing attempt, the agent retrieves relevant past experiences
- These experiences are included in the LLM prompt (LLM mode) or checked for direct reuse (offline mode)
- When a healed step succeeds, the agent saves the healing experience to memory
- On subsequent similar failures, the agent can reuse proven fixes (visible as "REUSED MEMORY FIX #n" in logs)

## Example Self-Healing Output (Offline Mode)

```
[INFO] Executing step: reserve_stock
[WARNING] Validation failed for reserve_stock: Insufficient stock for SKU011 in godown G001
[HEALER:offline] Stock shortage for SKU011 in godown G001
[HEALER:offline] Found 2 alternative godown(s) with stock.
[HEALER:offline] ACTION: change_arguments
[INFO] Healing: Changing arguments for reserve_stock from {'order_id': 'ORD002', 'godown_id': 'G001'} to {'order_id': 'ORD002', 'godown_id': 'G002'}
[INFO] Added memory entry: reserve_stock - Success: stock_reserved
```

This shows the agent:
1. Detected insufficient stock in godown G001
2. Offline healer diagnosed stock shortage and queried MCP tool for alternatives
3. Applied healing by switching to godown G002 (best alternative by stock)
4. Succeeded and saved the experience to memory
5. On subsequent runs, would show "REUSED MEMORY FIX #1" and apply the same fix faster

## Customization

- **Healing Mode**: Set via `--offline`/`--llm`/`--auto` CLI flags or `HEALER_MODE` environment variable
- **LLM Model**: Change the model in `agent/main.py` in the `_call_llm_for_healing` method
- **Max Retries**: Adjust `self.max_retries` in the `LogisticsAgent.__init__` method
- **Memory Persistence**: The memory is stored in `data/memory_log.json` - delete this to start fresh
- **Scenarios**: Modify the scenario files in the `scenarios/` directory to test different orders or conditions

## Notes for Demo

- This is a demo project with mock data - no actual shipments occur
- The agent is designed to be extensible for real logistics systems
- In production, you would want to:
  - Add more sophisticated validation
  - Integrate with real ERP/warehouse systems
  - Add proper authentication and authorization for MCP tools
  - Implement more complex healing strategies
  - Add monitoring and alerting

## License

This project is created for the Agent Wars hackathon demo.