import json
import random
from datetime import datetime, timedelta

def generate_seed_data():
    # Godowns
    godowns = [
        {"id": "G001", "name": "Chennai Godown", "location": "Chennai", "pin": "600001"},
        {"id": "G002", "name": "Bengaluru Godown", "location": "Bengaluru", "pin": "560001"},
        {"id": "G003", "name": "Hyderabad Godown", "location": "Hyderabad", "pin": "500001"}
    ]

    # SKUs (20 items)
    skus = []
    categories = ["Electronics", "Apparel", "Home & Kitchen", "Books", "Sports"]
    for i in range(1, 21):
        skus.append({
            "sku": f"SKU{i:03d}",
            "name": f"Product {i}",
            "category": random.choice(categories),
            "unit_price": round(random.uniform(10.0, 500.0), 2)
        })

    # Inventory levels per godown
    inventory = []
    for godown in godowns:
        for sku in skus:
            # Different stock levels per godown
            stock = random.randint(0, 100) if godown["id"] == "G001" else \
                    random.randint(10, 80) if godown["id"] == "G002" else \
                    random.randint(20, 120)
            inventory.append({
                "godown_id": godown["id"],
                "sku": sku["sku"],
                "stock": stock,
                "last_updated": datetime.now().isoformat()
            })

    # Orders (15 orders)
    orders = []
    statuses = ["pending", "confirmed", "picked", "packed", "shipped", "delivered"]
    for i in range(1, 16):
        order_skus = random.sample(skus, k=random.randint(1, 5))
        items = []
        for sku in order_skus:
            items.append({
                "sku": sku["sku"],
                "quantity": random.randint(1, 10),
                "unit_price": sku["unit_price"]
            })

        total_amount = sum(item["quantity"] * item["unit_price"] for item in items)

        orders.append({
            "order_id": f"ORD{i:03d}",
            "customer_name": f"Customer {i}",
            "customer_pin": random.choice(["600001", "560001", "500001", "400001", "700001"]),
            "items": items,
            "total_amount": round(total_amount, 2),
            "status": random.choice(statuses),
            "created_at": (datetime.now() - timedelta(days=random.randint(0, 30))).isoformat(),
            "updated_at": datetime.now().isoformat()
        })

    # Carriers (4 carriers)
    carriers = [
        {"id": "C001", "name": "FastTrack Logistics", "speed": "express", "cost_per_km": 15.0, "coverage": ["600001", "560001", "500001"]},
        {"id": "C002", "name": "Standard Shipping Co", "speed": "standard", "cost_per_km": 10.0, "coverage": ["600001", "560001", "500001", "400001", "700001"]},
        {"id": "C003", "name": "Economy Transport", "speed": "economy", "cost_per_km": 5.0, "coverage": ["600001", "560001"]},
        {"id": "C004", "name": "Premium Delivery", "speed": "premium", "cost_per_km": 20.0, "coverage": ["600001", "560001", "500001", "400001", "700001", "300001"]}
    ]

    # Save all data
    data = {
        "godowns": godowns,
        "skus": skus,
        "inventory": inventory,
        "orders": orders,
        "carriers": carriers
    }

    with open("data/seed_data.json", "w") as f:
        json.dump(data, f, indent=2)

    print("Seed data generated successfully!")
    return data

if __name__ == "__main__":
    generate_seed_data()