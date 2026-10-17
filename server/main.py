import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from fastmcp import FastMCP
from pydantic import BaseModel

# Initialize MCP server
mcp = FastMCP("Logistics Handler")

# Database setup
script_dir = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(script_dir, "..", "data", "logistics.db")

def init_db():
    """Initialize the database with seed data"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS godowns (
            id TEXT PRIMARY KEY,
            name TEXT,
            location TEXT,
            pin TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS skus (
            sku TEXT PRIMARY KEY,
            name TEXT,
            category TEXT,
            unit_price REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            godown_id TEXT,
            sku TEXT,
            stock INTEGER,
            last_updated TEXT,
            PRIMARY KEY (godown_id, sku),
            FOREIGN KEY (godown_id) REFERENCES godowns(id),
            FOREIGN KEY (sku) REFERENCES skus(sku)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            customer_name TEXT,
            customer_pin TEXT,
            items TEXT,  -- JSON string
            total_amount REAL,
            status TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS carriers (
            id TEXT PRIMARY KEY,
            name TEXT,
            speed TEXT,
            cost_per_km REAL,
            coverage TEXT  -- JSON string
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shipments (
            shipment_id TEXT PRIMARY KEY,
            order_id TEXT,
            carrier_id TEXT,
            status TEXT,
            tracking_number TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    ''')

    # Load seed data if tables are empty
    cursor.execute("SELECT COUNT(*) FROM godowns")
    if cursor.fetchone()[0] == 0:
        seed_data_path = os.path.join(script_dir, "..", "data", "seed_data.json")
        with open(seed_data_path, "r") as f:
            seed_data = json.load(f)

        # Insert godowns
        for godown in seed_data["godowns"]:
            cursor.execute(
                "INSERT INTO godowns (id, name, location, pin) VALUES (?, ?, ?, ?)",
                (godown["id"], godown["name"], godown["location"], godown["pin"])
            )

        # Insert SKUs
        for sku in seed_data["skus"]:
            cursor.execute(
                "INSERT INTO skus (sku, name, category, unit_price) VALUES (?, ?, ?, ?)",
                (sku["sku"], sku["name"], sku["category"], sku["unit_price"])
            )

        # Insert inventory
        for inv in seed_data["inventory"]:
            cursor.execute(
                "INSERT OR REPLACE INTO inventory (godown_id, sku, stock, last_updated) VALUES (?, ?, ?, ?)",
                (inv["godown_id"], inv["sku"], inv["stock"], inv["last_updated"])
            )

        # Insert orders
        for order in seed_data["orders"]:
            cursor.execute(
                """INSERT INTO orders
                   (order_id, customer_name, customer_pin, items, total_amount, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order["order_id"],
                    order["customer_name"],
                    order["customer_pin"],
                    json.dumps(order["items"]),
                    order["total_amount"],
                    order["status"],
                    order["created_at"],
                    order["updated_at"]
                )
            )

        # Insert carriers
        for carrier in seed_data["carriers"]:
            cursor.execute(
                "INSERT INTO carriers (id, name, speed, cost_per_km, coverage) VALUES (?, ?, ?, ?, ?)",
                (
                    carrier["id"],
                    carrier["name"],
                    carrier["speed"],
                    carrier["cost_per_km"],
                    json.dumps(carrier["coverage"])
                )
            )

    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Initialize database on startup
init_db()

# MCP Tools
@mcp.tool()
def get_order(order_id: str) -> dict:
    """Get order details by order ID"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "order_id": row["order_id"],
            "customer_name": row["customer_name"],
            "customer_pin": row["customer_pin"],
            "items": json.loads(row["items"]),
            "total_amount": row["total_amount"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }
    return {"error": f"Order {order_id} not found"}

@mcp.tool()
def check_inventory(sku: str) -> dict:
    """Check inventory levels for a SKU across all godowns"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT g.name as godown_name, g.location, i.stock
        FROM inventory i
        JOIN godowns g ON i.godown_id = g.id
        WHERE i.sku = ?
    """, (sku,))

    rows = cursor.fetchall()
    conn.close()

    inventory = {}
    total_stock = 0
    for row in rows:
        inventory[row["godown_name"]] = {
            "location": row["location"],
            "stock": row["stock"]
        }
        total_stock += row["stock"]

    return {
        "sku": sku,
        "inventory": inventory,
        "total_stock": total_stock
    }

@mcp.tool()
def reserve_stock(order_id: str, godown_id: str) -> dict:
    """Reserve stock for an order from a specific godown"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get order details
    cursor.execute("SELECT items FROM orders WHERE order_id = ?", (order_id,))
    order_row = cursor.fetchone()

    if not order_row:
        conn.close()
        return {"error": f"Order {order_id} not found"}

    items = json.loads(order_row["items"])

    # Check and reserve stock for each item
    reserved_items = []
    for item in items:
        sku = item["sku"]
        quantity = item["quantity"]

        cursor.execute("""
            SELECT stock FROM inventory
            WHERE godown_id = ? AND sku = ?
        """, (godown_id, sku))

        stock_row = cursor.fetchone()
        if not stock_row or stock_row["stock"] < quantity:
            conn.close()
            return {
                "error": f"Insufficient stock for {sku} in godown {godown_id}",
                "available": stock_row["stock"] if stock_row else 0,
                "required": quantity
            }

        # Reserve stock (reduce available stock)
        new_stock = stock_row["stock"] - quantity
        cursor.execute(
            "UPDATE inventory SET stock = ?, last_updated = ? WHERE godown_id = ? AND sku = ?",
            (new_stock, datetime.now().isoformat(), godown_id, sku)
        )

        reserved_items.append({
            "sku": sku,
            "quantity": quantity,
            "reserved_from": godown_id
        })

    # Update order status
    cursor.execute(
        "UPDATE orders SET status = 'confirmed', updated_at = ? WHERE order_id = ?",
        (datetime.now().isoformat(), order_id)
    )

    conn.commit()
    conn.close()

    return {
        "order_id": order_id,
        "godown_id": godown_id,
        "reserved_items": reserved_items,
        "status": "confirmed"
    }

@mcp.tool()
def pack_order(order_id: str) -> dict:
    """Mark an order as packed"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return {"error": f"Order {order_id} not found"}

    if row["status"] != "confirmed":
        conn.close()
        return {"error": f"Order {order_id} must be confirmed before packing. Current status: {row['status']}"}

    cursor.execute(
        "UPDATE orders SET status = 'packed', updated_at = ? WHERE order_id = ?",
        (datetime.now().isoformat(), order_id)
    )

    conn.commit()
    conn.close()

    return {
        "order_id": order_id,
        "status": "packed",
        "message": "Order packed successfully"
    }

@mcp.tool()
def list_carriers(destination_pin: str) -> dict:
    """List available carriers for a destination pincode"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM carriers")
    rows = cursor.fetchall()
    conn.close()

    available_carriers = []
    for row in rows:
        coverage = json.loads(row["coverage"])
        if destination_pin in coverage:
            available_carriers.append({
                "id": row["id"],
                "name": row["name"],
                "speed": row["speed"],
                "cost_per_km": row["cost_per_km"],
                "coverage": coverage
            })

    return {
        "destination_pin": destination_pin,
        "available_carriers": available_carriers,
        "count": len(available_carriers)
    }

@mcp.tool()
def book_shipment(order_id: str, carrier_id: str) -> dict:
    """Book a shipment with a carrier"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get order details
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order_row = cursor.fetchone()

    if not order_row:
        conn.close()
        return {"error": f"Order {order_id} not found"}

    if order_row["status"] != "packed":
        conn.close()
        return {"error": f"Order {order_id} must be packed before shipping. Current status: {order_row['status']}"}

    # Get carrier details
    cursor.execute("SELECT * FROM carriers WHERE id = ?", (carrier_id,))
    carrier_row = cursor.fetchone()

    if not carrier_row:
        conn.close()
        return {"error": f"Carrier {carrier_id} not found"}

    # Generate shipment ID and tracking number
    import uuid
    shipment_id = f"SHIP{uuid.uuid4().hex[:8].upper()}"
    tracking_number = f"TRK{uuid.uuid4().hex[:10].upper()}"

    # Insert shipment record
    cursor.execute(
        """INSERT INTO shipments
           (shipment_id, order_id, carrier_id, status, tracking_number, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            shipment_id,
            order_id,
            carrier_id,
            "shipped",
            tracking_number,
            datetime.now().isoformat(),
            datetime.now().isoformat()
        )
    )

    # Update order status
    cursor.execute(
        "UPDATE orders SET status = 'shipped', updated_at = ? WHERE order_id = ?",
        (datetime.now().isoformat(), order_id)
    )

    conn.commit()
    conn.close()

    return {
        "shipment_id": shipment_id,
        "order_id": order_id,
        "carrier_id": carrier_id,
        "carrier_name": carrier_row["name"],
        "tracking_number": tracking_number,
        "status": "shipped"
    }

@mcp.tool()
def track_shipment(shipment_id: str) -> dict:
    """Track a shipment by shipment ID"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.*, o.order_id, o.customer_name, c.name as carrier_name
        FROM shipments s
        JOIN orders o ON s.order_id = o.order_id
        JOIN carriers c ON s.carrier_id = c.id
        WHERE s.shipment_id = ?
    """, (shipment_id,))

    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "shipment_id": row["shipment_id"],
            "order_id": row["order_id"],
            "customer_name": row["customer_name"],
            "carrier_name": row["carrier_name"],
            "tracking_number": row["tracking_number"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }
    return {"error": f"Shipment {shipment_id} not found"}

@mcp.tool()
def report_issue(order_id: str, issue_type: str, details: str) -> dict:
    """Report an issue with an order"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT order_id FROM orders WHERE order_id = ?", (order_id,))
    if not cursor.fetchone():
        conn.close()
        return {"error": f"Order {order_id} not found"}

    # In a real system, this would go to an issues table
    # For now, we'll just log it and update order status if needed
    conn.close()

    return {
        "order_id": order_id,
        "issue_type": issue_type,
        "details": details,
        "reported_at": datetime.now().isoformat(),
        "status": "issue_reported"
    }

if __name__ == "__main__":
    mcp.run()