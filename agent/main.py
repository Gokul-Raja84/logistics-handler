#!/usr/bin/env python3
"""
Autonomous Logistics Handler Agent
Implements the Plan -> Act -> Observe -> Validate -> Reflect -> Retry/Adapt loop
"""

import os
import json
import asyncio
import logging
import argparse
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

# MCP client imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# LLM client for healing
try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    print("Warning: google-genai not available. Healing will use rule-based fallback.")

# Offline healer
from offline_healer import OfflineHealer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AgentState(Enum):
    PENDING = "pending"
    PLANNING = "planning"
    ACTING = "acting"
    OBSERVING = "observing"
    VALIDATING = "validating"
    REFLECTING = "reflecting"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class MemoryEntry:
    """Represents a learning memory entry"""
    timestamp: str
    order_id: str
    step: str
    action_taken: str
    outcome: str
    lesson_learned: str
    success: bool

@dataclass
class ValidationResult:
    """Result of validating an action"""
    is_valid: bool
    expected_state: str
    actual_state: str
    error_message: Optional[str] = None
    suggested_fix: Optional[str] = None

class LogisticsAgent:
    def __init__(self, healer_mode: str = "auto"):
        self.mcp_session: Optional[ClientSession] = None
        self.memory_log: List[MemoryEntry] = []
        self.max_retries = 3
        self.current_order_id: Optional[str] = None
        self.state = AgentState.PENDING
        self.healer_mode = healer_mode  # "llm", "offline", or "auto"

        # LLM client for healing
        self.llm_client = None
        if GENAI_AVAILABLE:
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if api_key:
                try:
                    self.llm_client = genai.Client(api_key=api_key)
                    logger.info("LLM client initialized for healing")
                except Exception as e:
                    logger.warning(f"Failed to initialize LLM client: {e}")
                    self.llm_client = None
            else:
                logger.warning("No Google/Gemini API key found in environment variables")
                self.llm_client = None
        else:
            self.llm_client = None

        # Load existing memory if available
        self.load_memory()

    def load_memory(self):
        """Load memory log from file"""
        try:
            if os.path.exists("data/memory_log.json"):
                with open("data/memory_log.json", "r") as f:
                    data = json.load(f)
                    self.memory_log = [MemoryEntry(**entry) for entry in data]
                logger.info(f"Loaded {len(self.memory_log)} memory entries")
            else:
                self.memory_log = []
        except Exception as e:
            logger.warning(f"Could not load memory log: {e}")
            self.memory_log = []

    def save_memory(self):
        """Save memory log to file"""
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/memory_log.json", "w") as f:
                json.dump([asdict(entry) for entry in self.memory_log], f, indent=2)
        except Exception as e:
            logger.error(f"Could not save memory log: {e}")

    def add_memory_entry(self, order_id: str, step: str, action_taken: str,
                        outcome: str, lesson_learned: str, success: bool):
        """Add a new entry to the memory log"""
        entry = MemoryEntry(
            timestamp=datetime.now().isoformat(),
            order_id=order_id,
            step=step,
            action_taken=action_taken,
            outcome=outcome,
            lesson_learned=lesson_learned,
            success=success
        )
        self.memory_log.append(entry)
        self.save_memory()
        logger.info(f"Added memory entry: {step} - {outcome}")

    def get_relevant_memories(self, order_id: str, step: str) -> List[MemoryEntry]:
        """Get relevant memories for similar situations"""
        relevant = []
        for entry in self.memory_log:
            # Look for similar steps or order-related memories
            if entry.step == step or entry.order_id == order_id:
                relevant.append(entry)
        # Return most recent 5 entries
        return relevant[-5:]

    def _get_known_godowns(self) -> List[str]:
        """Get known godown IDs from memory or seed data"""
        # Try to get from memory entries
        godowns = set()
        for entry in self.memory_log:
            # Look for godown IDs in action_taken or outcome
            if hasattr(entry, 'action_taken') and isinstance(entry.action_taken, str):
                # Extract godown IDs like G001, G002, etc.
                import re
                matches = re.findall(r'G\d{3}', entry.action_taken)
                godowns.update(matches)
            if hasattr(entry, 'outcome') and isinstance(entry.outcome, str):
                # Extract godown IDs like G001, G002, etc.
                import re
                matches = re.findall(r'G\d{3}', entry.outcome)
                godowns.update(matches)

        # If we found some, return them sorted
        if godowns:
            return sorted(list(godowns))

        # Return empty list - we'll let the caller handle the case where no godowns are known
        return []

    async def connect_to_mcp_server(self):
        """Connect to the MCP server"""
        try:
            server_params = StdioServerParameters(
                command="python",
                args=["main.py"],
                cwd=os.path.join(os.path.dirname(__file__), "..", "server")
            )

            self.stdio_context = stdio_client(server_params)
            self.read, self.write = await self.stdio_context.__aenter__()
            self.mcp_session = ClientSession(self.read, self.write)
            await self.mcp_session.__aenter__()

            # Initialize the session
            await self.mcp_session.initialize()
            logger.info("Connected to MCP server")

        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            raise

    async def disconnect_from_mcp_server(self):
        """Disconnect from the MCP server"""
        try:
            if self.mcp_session:
                await self.mcp_session.__aexit__(None, None, None)
            if hasattr(self, 'stdio_context'):
                await self.stdio_context.__aexit__(None, None, None)
            logger.info("Disconnected from MCP server")
        except Exception as e:
            logger.warning(f"Error during disconnection: {e}")

    async def call_mcp_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool and return the result"""
        if not self.mcp_session:
            raise Exception("Not connected to MCP server")

        try:
            result = await self.mcp_session.call_tool(tool_name, arguments)
            # Extract content from the result
            if hasattr(result, 'content'):
                # Handle different content types
                if isinstance(result.content, list) and len(result.content) > 0:
                    # If it's a list of content items, get the first one's text
                    first_content = result.content[0]
                    if hasattr(first_content, 'text'):
                        return json.loads(first_content.text)
                    else:
                        return {"text": str(first_content)}
                else:
                    return {"text": str(result.content)}
            else:
                return {"result": str(result)}

        except Exception as e:
            logger.error(f"MCP tool call failed: {tool_name} - {e}")
            raise

    def validate_step(self, step: str, expected_outcome: str, actual_result: dict) -> ValidationResult:
        """Validate the result of a step against expected outcome"""
        # Basic validation logic - can be expanded per step
        if "error" in actual_result:
            return ValidationResult(
                is_valid=False,
                expected_state=expected_outcome,
                actual_state="error",
                error_message=actual_result.get("error", "Unknown error"),
                suggested_fix="Check parameters and preconditions"
            )

        # Step-specific validation
        if step == "get_order":
            required_fields = ["order_id", "customer_name", "status"]
            if all(field in actual_result for field in required_fields):
                return ValidationResult(
                    is_valid=True,
                    expected_state=expected_outcome,
                    actual_state="order_retrieved"
                )

        elif step == "check_inventory":
            if "sku" in actual_result and "inventory" in actual_result:
                return ValidationResult(
                    is_valid=True,
                    expected_state=expected_outcome,
                    actual_state="inventory_checked"
                )

        elif step == "reserve_stock":
            if actual_result.get("status") == "confirmed":
                return ValidationResult(
                    is_valid=True,
                    expected_state=expected_outcome,
                    actual_state="stock_reserved"
                )

        elif step == "pack_order":
            if actual_result.get("status") == "packed":
                return ValidationResult(
                    is_valid=True,
                    expected_state=expected_outcome,
                    actual_state="order_packed"
                )

        elif step == "list_carriers":
            if "available_carriers" in actual_result:
                return ValidationResult(
                    is_valid=True,
                    expected_state=expected_outcome,
                    actual_state="carriers_listed"
                )

        elif step == "book_shipment":
            if actual_result.get("status") == "shipped":
                return ValidationResult(
                    is_valid=True,
                    expected_state=expected_outcome,
                    actual_state="shipment_booked"
                )

        elif step == "track_shipment":
            if "status" in actual_result:
                return ValidationResult(
                    is_valid=True,
                    expected_state=expected_outcome,
                    actual_state=f"shipment_tracked_{actual_result.get('status')}"
                )

        # Default validation - if no error, assume success
        return ValidationResult(
            is_valid=True,
            expected_state=expected_outcome,
            actual_state="completed"
        )

    async def reflect_and_adapt(self, step: str, validation_result: ValidationResult,
                               memories: List[MemoryEntry], attempt: int) -> dict:
        """Reflect on failure and adapt approach using LLM or offline reasoning"""

        # Get order context if available
        order_context = {}
        if self.current_order_id:
            # Try to get order details from memory or we could make a quick MCP call
            # For now, we'll get what we can from recent memories
            for mem in reversed(self.memory_log[-10:]):  # Last 10 entries
                if mem.order_id == self.current_order_id:
                    if "Retrieved order" in mem.outcome or "order_retrieved" in mem.outcome:
                        # Try to extract basic order info
                        pass
                    break

        # Prepare context for healing
        context = {
            "failed_step": step,
            "validation_error": validation_result.error_message or "Unknown error",
            "attempt_number": attempt + 1,
            "max_retries": self.max_retries,
            "order_id": self.current_order_id,
            "relevant_memories": [
                {
                    "step": mem.step,
                    "action_taken": mem.action_taken,
                    "outcome": mem.outcome,
                    "lesson_learned": mem.lesson_learned,
                    "success": mem.success
                }
                for mem in memories[:3]  # Top 3 relevant memories
            ]
        }

        # Add order context if we have it
        if self.current_order_id:
            # We could fetch the order again, but for now we'll leave it empty
            # The offline healer can make a call to get_order if needed
            pass

        # Healer selection based on mode
        if self.healer_mode == "llm":
            # LLM only mode
            if self.llm_client is not None:
                try:
                    llm_result = self._call_llm_for_healing(context)
                    if llm_result is not None:
                        logger.info(f"[HEALER:llm] LLM healing decision: {llm_result}")
                        return llm_result
                    else:
                        # LLM returned None, fallback to escalation
                        logger.warning("[HEALER:llm] LLM healing returned None, escalating")
                        return {
                            "diagnosis": "LLM healing failed to produce a decision",
                            "recovery_action": "escalate",
                            "new_arguments": {},
                            "tool_name": "",
                            "confidence": 0.0
                        }
                except Exception as e:
                    logger.warning(f"[HEALER:llm] LLM healing failed, escalating: {e}")
                    return {
                        "diagnosis": f"LLM healing error: {str(e)}",
                        "recovery_action": "escalate",
                        "new_arguments": {},
                        "tool_name": "",
                        "confidence": 0.0
                    }
            else:
                logger.warning("[HEALER:llm] LLM client not available, escalating")
                return {
                    "diagnosis": "LLM client not available",
                    "recovery_action": "escalate",
                    "new_arguments": {},
                    "tool_name": "",
                    "confidence": 0.0
                }

        elif self.healer_mode == "offline":
            # Offline only mode
            try:
                offline_healer = OfflineHealer(self.mcp_session, self.current_order_id or "")
                healing_decision = await offline_healer.heal(
                    failed_step=step,
                    tool_name=step,  # The tool that failed corresponds to the step name
                    arguments={},  # We'll get this from the step plan in the calling context
                    error_message=validation_result.error_message,
                    order_context=order_context
                )
                # Convert HealingDecision to dict
                result = {
                    "diagnosis": healing_decision.diagnosis,
                    "recovery_action": healing_decision.recovery_action,
                    "new_arguments": healing_decision.new_arguments,
                    "tool_name": healing_decision.tool_name,
                    "confidence": healing_decision.confidence
                }
                logger.info(f"[HEALER:offline] Offline healing decision: {result}")
                return result
            except Exception as e:
                logger.warning(f"[HEALER:offline] Offline healing failed: {e}")
                return {
                    "diagnosis": f"Offline healing error: {str(e)}",
                    "recovery_action": "escalate",
                    "new_arguments": {},
                    "tool_name": "",
                    "confidence": 0.0
                }
        else:  # auto mode
            # Try LLM first, then fallback to offline
            if self.llm_client is not None:
                try:
                    llm_result = self._call_llm_for_healing(context)
                    if llm_result is not None:
                        logger.info(f"[HEARER:llm] LLM healing decision: {llm_result}")
                        return llm_result
                    else:
                        logger.warning("[HEALER:auto] LLM returned None, trying offline healer")
                        # Fall through to offline
                except Exception as e:
                    logger.warning(f"[HEALER:auto] LLM healing failed, trying offline healer: {e}")
                    # Fall through to offline
            else:
                logger.warning("[HEALER:auto] LLM client not available, trying offline healer")

            # Try offline healer
            try:
                offline_healer = OfflineHealer(self.mcp_session, self.current_order_id or "")
                healing_decision = await offline_healer.heal(
                    failed_step=step,
                    tool_name=step,  # The tool that failed corresponds to the step name
                    arguments={},  # We'll get this from the step plan in the calling context
                    error_message=validation_result.error_message,
                    order_context=order_context
                )
                # Convert HealingDecision to dict
                result = {
                    "diagnosis": healing_decision.diagnosis,
                    "recovery_action": healing_decision.recovery_action,
                    "new_arguments": healing_decision.new_arguments,
                    "tool_name": healing_decision.tool_name,
                    "confidence": healing_decision.confidence
                }
                logger.info(f"[HEALER:offline] Offline healing decision (auto mode): {result}")
                return result
            except Exception as e:
                logger.warning(f"[HEALER:auto] Offline healing failed: {e}")
                return {
                    "diagnosis": f"Offline healing error: {str(e)}",
                    "recovery_action": "escalate",
                    "new_arguments": {},
                    "tool_name": "",
                    "confidence": 0.0
                }

    def _call_llm_for_healing(self, context: dict) -> Optional[dict]:
        """Call LLM to get healing decision"""
        try:
            # Create the prompt for LLM
            prompt = self._create_healing_prompt(context)

            # Configure generation settings for structured output
            config = {
                "temperature": 0.1,
                "max_output_tokens": 500,
            }

            # Generate response
            response = self.llm_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config=config
            )

            # Parse the response
            response_text = response.text.strip()

            # Try to extract JSON from the response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                try:
                    result = json.loads(json_str)
                    # Validate the result structure
                    if self._validate_healing_result(result):
                        return result
                    else:
                        logger.warning(f"LLM returned invalid structure: {result}")
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse LLM JSON response: {e}")
            else:
                logger.warning(f"No JSON found in LLM response: {response_text}")

        except Exception as e:
            logger.error(f"Error calling LLM for healing: {e}")

        return None

    def _create_healing_prompt(self, context: dict) -> str:
        """Create prompt for LLM healing"""
        order_id = context.get("order_id", "unknown")
        failed_step = context.get("failed_step", "unknown")
        error_msg = context.get("validation_error", "Unknown error")
        attempt_num = context.get("attempt_number", 1)
        max_retries = context.get("max_retries", 3)

        # Format relevant memories
        memories_text = ""
        relevant_memories = context.get("relevant_memories", [])
        if relevant_memories:
            memories_text = "\nRelevant past experiences:\n"
            for i, mem in enumerate(relevant_memories, 1):
                memories_text += f"{i}. Step: {mem['step']}\n"
                memories_text += f"   Action: {mem['action_taken']}\n"
                memories_text += f"   Outcome: {mem['outcome']}\n"
                memories_text += f"   Lesson: {mem['lesson_learned']}\n"
                memories_text += f"   Success: {mem['success']}\n\n"
        else:
            memories_text = "\nNo relevant past experiences found.\n"

        prompt = f"""You are an AI agent healing a failed step in a logistics automation process.

FAILED STEP INFORMATION:
- Step: {failed_step}
- Error: {error_msg}
- Attempt: {attempt_num} of {max_retries}
- Order ID: {order_id}

{memories_text}

Based on the error and past experiences, provide a healing decision in JSON format with these exact fields:
{{
  "diagnosis": "Brief explanation of what went wrong",
  "recovery_action": one of ["change_arguments", "switch_tool", "retry_same", "escalate"],
  "new_arguments": {{}} (arguments to use for retry, empty if not changing arguments),
  "tool_name": "" (tool to use for retry, empty if same tool),
  "confidence": 0.0-1.0 (your confidence in this decision)
}}

VALIDATION RULES:
- If recovery_action is "change_arguments": provide new_arguments dict with updated values
- If recovery_action is "switch_tool": provide different tool_name and optionally new_arguments
- If recovery_action is "retry_same": keep same tool and arguments (new_arguments can be empty)
- If recovery_action is "escalate": should_retry will be false, new_arguments and tool_name empty

Respond ONLY with the JSON object, no additional text."""

        return prompt

    def _validate_healing_result(self, result: dict) -> bool:
        """Validate LLM healing result structure"""
        required_fields = ["diagnosis", "recovery_action", "new_arguments", "tool_name", "confidence"]
        if not all(field in result for field in required_fields):
            return False

        valid_actions = ["change_arguments", "switch_tool", "retry_same", "escalate"]
        if result["recovery_action"] not in valid_actions:
            return False

        if not isinstance(result["new_arguments"], dict):
            return False

        if not isinstance(result["tool_name"], str):
            return False

        if not isinstance(result["confidence"], (int, float)) or not (0.0 <= result["confidence"] <= 1.0):
            return False

        return True

    def _rule_based_healing(self, step: str, validation_result: ValidationResult,
                          attempt: int) -> dict:
        """Fallback rule-based healing"""
        error_msg = validation_result.error_message or ""

        healing_actions = {
            "Insufficient stock": {
                "action": "reserve_from_alternative_godown",
                "description": "Try reserving stock from a different godown with available inventory"
            },
            "must be confirmed before packing": {
                "action": "ensure_order_confirmed",
                "description": "Make sure order is confirmed before attempting to pack"
            },
            "must be packed before shipping": {
                "action": "ensure_order_packed",
                "description": "Make sure order is packed before attempting to ship"
            }
        }

        # Check if we match any known healing patterns
        for pattern, action in healing_actions.items():
            if pattern in error_msg:
                return {
                    "healing_action": action["action"],
                    "description": action["description"],
                    "should_retry": True
                }

        # If no specific healing pattern, generic retry with potential alternatives
        if attempt < self.max_retries:
            return {
                "healing_action": "retry_with_delay",
                "description": f"Retry attempt {attempt + 1} after brief delay",
                "should_retry": True
            }
        else:
            return {
                "healing_action": "escalate_issue",
                "description": "Max retries exceeded, escalate to human intervention",
                "should_retry": False
            }

    def _validate_healing_plan(self, recovery_action: str, new_arguments: dict,
                             tool_name: str, validation_result: ValidationResult) -> bool:
        """Validate that the healing plan is safe and sensible"""
        valid_actions = ["change_arguments", "switch_tool", "retry_same", "escalate"]
        if recovery_action not in valid_actions:
            return False

        if not isinstance(new_arguments, dict):
            return False

        if not isinstance(tool_name, str):
            return False

        # Additional validation: for logistics agent, we know what tools are valid
        valid_tools = ["get_order", "check_inventory", "reserve_stock", "pack_order",
                      "list_carriers", "book_shipment", "track_shipment", "report_issue"]
        if tool_name and tool_name not in valid_tools:
            logger.warning(f"Invalid tool name in healing plan: {tool_name}")
            return False

        return True

    def _apply_rule_based_healing(self, step_name: str, arguments: dict,
                                validation_result: ValidationResult) -> dict:
        """Apply rule-based healing when LLM plan is invalid"""
        logger.info(f"Applying rule-based healing for {step_name}")

        if step_name == "reserve_stock" and "Insufficient stock" in validation_result.error_message:
            # Try alternative godowns
            # Get known godowns from memory or use a reasonable default
            known_godowns = self._get_known_godowns()
            current_godown = arguments.get("godown_id", known_godowns[0] if known_godowns else "")

            # If we don't have a current godown or known godowns, we can't do much
            if not known_godowns or not current_godown:
                # Leave arguments as is - the offline healer will handle discovery
                return arguments

            if current_godown in known_godowns:
                try:
                    current_index = known_godowns.index(current_godown)
                    # Try next godown in rotation
                    next_index = (current_index + 1) % len(known_godowns)
                    arguments["godown_id"] = known_godowns[next_index]
                    logger.info(f"Rule-based healing: Switching from {current_godown} to {arguments['godown_id']} for stock reservation")
                except ValueError:
                    # Fallback to first known godown
                    arguments["godown_id"] = known_godowns[0]
                    logger.info(f"Rule-based healing: Falling back to {arguments['godown_id']} for stock reservation")
            else:
                # Current godown not in known list, use first known godown
                arguments["godown_id"] = known_godowns[0]
                logger.info(f"Rule-based healing: Using {arguments['godown_id']} for stock reservation")

        elif step_name == "pack_order" and "must be confirmed before packing" in validation_result.error_message:
            # In a real implementation, we might trigger confirmation
            pass

        elif step_name == "book_shipment" and "must be packed before shipping" in validation_result.error_message:
            # In a real implementation, we might trigger packing
            pass

        return arguments

    async def execute_step_with_healing(self, step_name: str, tool_name: str,
                                      arguments: dict, expected_outcome: str) -> dict:
        """Execute a step with self-healing capabilities"""
        self.state = AgentState.ACTING
        logger.info(f"Executing step: {step_name}")

        # Get relevant memories for this step
        relevant_memories = self.get_relevant_memories(self.current_order_id, step_name)

        for attempt in range(self.max_retries + 1):
            try:
                # Act: Call the MCP tool
                result = await self.call_mcp_tool(tool_name, arguments)

                # Observe: We have the result
                self.state = AgentState.OBSERVING

                # Validate: Check if result matches expectations
                validation_result = self.validate_step(step_name, expected_outcome, result)

                if validation_result.is_valid:
                    # Success! Learn from this
                    lesson = f"Successfully executed {step_name} on attempt {attempt + 1}"
                    self.add_memory_entry(
                        self.current_order_id,
                        step_name,
                        f"Called {tool_name} with {arguments}",
                        f"Success: {validation_result.actual_state}",
                        lesson,
                        True
                    )

                    self.state = AgentState.COMPLETED if attempt == self.max_retries else AgentState.PENDING
                    return result
                else:
                    # Validation failed - need to heal
                    logger.warning(f"Validation failed for {step_name}: {validation_result.error_message}")

                    if attempt == self.max_retries:
                        # Max retries reached
                        self.add_memory_entry(
                            self.current_order_id,
                            step_name,
                            f"Called {tool_name} with {arguments}",
                            f"Failed after {attempt + 1} attempts: {validation_result.error_message}",
                            "Max retries exceeded, considering alternative approaches",
                            False
                        )

                        # Escalate issue
                        await self.report_issue(
                            self.current_order_id,
                            "process_failure",
                            f"Failed to complete {step_name} after {self.max_retries + 1} attempts: {validation_result.error_message}"
                        )

                        self.state = AgentState.FAILED
                        return {"error": validation_result.error_message, "escalated": True}

                    # Reflect and adapt for next attempt
                    self.state = AgentState.REFLECTING
                    healing_plan = await self.reflect_and_adapt(
                        step_name, validation_result, relevant_memories, attempt
                    )

                    logger.info(f"Healing plan: {healing_plan['description']}")

                    self.add_memory_entry(
                        self.current_order_id,
                        step_name,
                        f"Called {tool_name} with {arguments}",
                        f"Failed attempt {attempt + 1}: {validation_result.error_message}",
                        f"Will try: {healing_plan['description']}",
                        False
                    )

                    # Apply healing and prepare for retry
                    if healing_plan.get("should_retry"):
                        self.state = AgentState.RETRYING
                        # Wait briefly before retry (in real implementation, might adjust parameters)
                        await asyncio.sleep(1 * (attempt + 1))  # Increasing delay

                        # Modify arguments based on healing plan
                        arguments = self.apply_healing_to_arguments(
                            step_name, arguments, healing_plan, validation_result
                        )
                    else:
                        break

            except Exception as e:
                logger.error(f"Exception in step {step_name}: {e}")
                if attempt == self.max_retries:
                    self.add_memory_entry(
                        self.current_order_id,
                        step_name,
                        f"Called {tool_name} with {arguments}",
                        f"Exception after {attempt + 1} attempts: {str(e)}",
                        "Technical failure requiring investigation",
                        False
                    )
                    self.state = AgentState.FAILED
                    return {"error": str(e), "exception": True}
                else:
                    await asyncio.sleep(1 * (attempt + 1))

        self.state = AgentState.FAILED
        return {"error": "Max retries exceeded"}

    def apply_healing_to_arguments(self, step_name: str, arguments: dict,
                                 healing_plan: dict, validation_result: ValidationResult) -> dict:
        """Modify arguments based on healing plan from LLM"""
        # Extract the healing decision from LLM
        recovery_action = healing_plan.get("recovery_action", "retry_same")
        new_arguments = healing_plan.get("new_arguments", {})
        tool_name = healing_plan.get("tool_name", "")

        # Validate the healing plan
        if not self._validate_healing_plan(recovery_action, new_arguments, tool_name, validation_result):
            logger.warning(f"Invalid healing plan from LLM: {healing_plan}. Falling back to rule-based.")
            return self._apply_rule_based_healing(step_name, arguments, validation_result)

        # Apply the healing plan
        if recovery_action == "change_arguments":
            # Merge new arguments with existing ones
            updated_args = arguments.copy()
            updated_args.update(new_arguments)
            logger.info(f"Healing: Changing arguments for {step_name} from {arguments} to {updated_args}")
            return updated_args

        elif recovery_action == "switch_tool":
            # For now, we keep the same tool but note that in a full implementation
            # we would switch tools. For this logistics agent, most healing involves
            # changing arguments rather than tools.
            updated_args = arguments.copy()
            updated_args.update(new_arguments)
            logger.info(f"Healing: Switching tool and updating arguments for {step_name}")
            return updated_args

        elif recovery_action == "retry_same":
            # Keep same arguments, maybe add a small delay or variation
            logger.info(f"Healing: Retrying {step_name} with same arguments")
            return arguments

        elif recovery_action == "escalate":
            # Don't retry, but we still return arguments for consistency
            logger.info(f"Healing: Escalating {step_name} - no retry")
            return arguments

        # Default fallback
        return arguments

    async def report_issue(self, order_id: str, issue_type: str, details: str) -> dict:
        """Report an issue using the MCP tool"""
        try:
            result = await self.call_mcp_tool("report_issue", {
                "order_id": order_id,
                "issue_type": issue_type,
                "details": details
            })
            logger.info(f"Issue reported: {issue_type}")
            return result
        except Exception as e:
            logger.error(f"Failed to report issue: {e}")
            return {"error": str(e)}

    async def process_order(self, order_id: str) -> dict:
        """Main order processing loop implementing Plan->Act->Observe->Validate->Reflect->Retry/Adapt"""
        logger.info(f"Starting to process order: {order_id}")
        self.current_order_id = order_id
        self.state = AgentState.PLANNING

        # Plan: Define the steps we need to execute
        steps = [
            {
                "name": "get_order",
                "tool": "get_order",
                "arguments": {"order_id": order_id},
                "expected_outcome": "order_details_retrieved"
            },
            {
                "name": "check_inventory",
                "tool": "check_inventory",
                "arguments": {"sku": ""},  # Will be filled after getting order
                "expected_outcome": "inventory_levels_known"
            },
            {
                "name": "reserve_stock",
                "tool": "reserve_stock",
                "arguments": {"order_id": order_id, "godown_id": ""},  # Will be filled
                "expected_outcome": "stock_reserved_from_godown"
            },
            {
                "name": "pack_order",
                "tool": "pack_order",
                "arguments": {"order_id": order_id},
                "expected_outcome": "order_packed"
            },
            {
                "name": "list_carriers",
                "tool": "list_carriers",
                "arguments": {"destination_pin": ""},  # Will be filled
                "expected_outcome": "available_carriers_identified"
            },
            {
                "name": "book_shipment",
                "tool": "book_shipment",
                "arguments": {"order_id": order_id, "carrier_id": ""},  # Will be filled
                "expected_outcome": "shipment_booked_with_carrier"
            },
            {
                "name": "track_shipment",
                "tool": "track_shipment",
                "arguments": {"shipment_id": ""},  # Will be filled
                "expected_outcome": "shipment_tracked"
            }
        ]

        # Execute steps sequentially
        step_results = {}

        for i, step_plan in enumerate(steps):
            step_name = step_plan["name"]
            logger.info(f"--- Step {i+1}/{len(steps)}: {step_name} ---")

            # Prepare arguments based on previous results
            arguments = step_plan["arguments"].copy()

            # Fill in dynamic arguments from previous steps
            if step_name == "check_inventory" and "get_order" in step_results:
                # Get first SKU from order items
                order_items = step_results["get_order"].get("items", [])
                if order_items:
                    arguments["sku"] = order_items[0]["sku"]
                else:
                    arguments["sku"] = "SKU001"  # fallback - this is acceptable as it's just a placeholder

            elif step_name == "reserve_stock" and "check_inventory" in step_results:
                # Select godown with most stock
                inventory_data = step_results["check_inventory"].get("inventory", {})
                if inventory_data:
                    # Find godown with maximum stock
                    best_godown = max(inventory_data.items(),
                                    key=lambda x: x[1]["stock"]) if inventory_data else None
                    if best_godown:
                        arguments["godown_id"] = best_godown[0]  # This needs mapping from name to ID
                    else:
                        # No inventory data, leave empty to trigger healing if needed
                        arguments["godown_id"] = ""
                else:
                    # No inventory data, leave empty to trigger healing if needed
                    arguments["godown_id"] = ""

            elif step_name == "list_carriers" and "get_order" in step_results:
                arguments["destination_pin"] = step_results["get_order"].get("customer_pin", "600001")

            elif step_name == "book_shipment" and "list_carriers" in step_results:
                carriers = step_results["list_carriers"].get("available_carriers", [])
                if carriers:
                    # Select first available carrier (could be smarter - fastest/cheapest)
                    arguments["carrier_id"] = carriers[0]["id"]
                else:
                    # No carriers available, leave empty to trigger healing if needed
                    arguments["carrier_id"] = ""

            elif step_name == "track_shipment" and "book_shipment" in step_results:
                arguments["shipment_id"] = step_results["book_shipment"].get("shipment_id", "")

            # Execute the step with self-healing
            result = await self.execute_step_with_healing(
                step_plan["name"],
                step_plan["tool"],
                arguments,
                step_plan["expected_outcome"]
            )

            step_results[step_name] = result

            # Check if step failed critically
            if "error" in result and not result.get("should_retry", False):
                logger.error(f"Step {step_name} failed critically: {result.get('error')}")
                break

        # Determine final outcome
        final_status = "completed" if all(not r.get("error") for r in step_results.values() if isinstance(r, dict)) else "failed"

        # Add overall memory entry
        self.add_memory_entry(
            order_id,
            "complete_order_process",
            f"Processed order through {len([s for s in steps if s['name'] in step_results])} steps",
            f"Final status: {final_status}",
            "Order processing completed" if final_status == "completed" else "Order processing failed",
            final_status == "completed"
        )

        self.state = AgentState.COMPLETED if final_status == "completed" else AgentState.FAILED

        return {
            "order_id": order_id,
            "final_status": final_status,
            "step_results": step_results,
            "processed_at": datetime.now().isoformat()
        }

    async def run_demo_scenario(self, scenario_name: str, order_id: str):
        """Run a demo scenario"""
        logger.info(f"=== Running Demo Scenario: {scenario_name} ===")

        try:
            await self.connect_to_mcp_server()
            result = await self.process_order(order_id)

            logger.info(f"Scenario {scenario_name} completed with status: {result['final_status']}")
            return result

        finally:
            await self.disconnect_from_mcp_server()

async def main():
    """Main entry point for the agent"""
    parser = argparse.ArgumentParser(description='Logistics Handler Agent')
    parser.add_argument('--offline', action='store_true', help='Use offline healing mode only')
    parser.add_argument('--llm', action='store_true', help='Use LLM healing mode only')
    parser.add_argument('--auto', action='store_true', help='Use auto healing mode (LLM with offline fallback)')
    args = parser.parse_args()

    # Determine healer mode
    healer_mode = "auto"  # default
    if args.offline:
        healer_mode = "offline"
    elif args.llm:
        healer_mode = "llm"
    elif args.auto:
        healer_mode = "auto"
    # Also check environment variable
    env_mode = os.getenv("HEALER_MODE", "auto").lower()
    if env_mode in ["llm", "offline", "auto"]:
        healer_mode = env_mode
    # Command line argument overrides environment variable
    if args.offline or args.llm or args.auto:
        if args.offline:
            healer_mode = "offline"
        elif args.llm:
            healer_mode = "llm"
        elif args.auto:
            healer_mode = "auto"

    agent = LogisticsAgent(healer_mode=healer_mode)

    # For demo purposes, process a sample order
    # In reality, this would take order_id as a command line argument
    sample_order_id = "ORD001"

    result = await agent.run_demo_scenario("Happy Path Demo", sample_order_id)

    print("\n" + "="*50)
    print("LOGISTICS AGENT DEMO RESULT")
    print("="*50)
    print(f"Order ID: {result['order_id']}")
    print(f"Final Status: {result['final_status']}")
    print(f"Processed At: {result['processed_at']}")

    print("\nStep Results:")
    for step_name, step_result in result['step_results'].items():
        status = "[PASS]" if not step_result.get("error") else "[FAIL]"
        print(f"  {step_name}: {status}")
        if step_result.get("error"):
            # Safely print error without Unicode issues
            error_msg = str(step_result.get('error', ''))
            # Remove or replace problematic Unicode characters
            error_msg = ''.join(c if ord(c) < 128 else '?' for c in error_msg)
            print(f"    Error: {error_msg}")

    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())