"""
Synthetic data generator for "Souq & Co" — a fictional supplements and fitness retailer
selling in Saudi Arabia and India.

Builds two domain packs used all year by the agentic ops platform:
  Commerce pack:  customers, products, orders, order_items, returns, policies (Markdown)
  Payments pack:  transactions, chargebacks, refund_rules, kyc_notes

Then breaks a little of the data ON PURPOSE (missing fields, duplicates, mismatches,
bad dates) and records every break in data/mess_log.csv — the answer key for evals.

Run from the repo root:
    pip install faker
    python scripts/generate_data.py

Seeded, so every run produces exactly the same data.
"""

import csv
import os
import random
from datetime import date, timedelta

from faker import Faker

# =============================================================================
# 0. Setup
# =============================================================================
SEED = 42
random.seed(SEED)          # fixes Python's dice (random.choice, random.random...)
Faker.seed(SEED)           # fixes Faker's dice (names, emails, dates, uuids)

TODAY = date(2026, 10, 1)  # fixed "today" so the data never changes over time

fake_in = Faker("en_IN")   # Indian names, cities, phone numbers
fake_sa = Faker("ar_SA")   # Saudi names (Arabic script)

DATA_DIR = "data"
POLICY_DIR = "policies"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(POLICY_DIR, exist_ok=True)

N_CUSTOMERS = 500
N_PRODUCTS = 200
N_ORDERS = 2000
RETURN_RATE = 0.08
N_CHARGEBACKS = 20


def cap(d):
    """Nothing can happen after 'today'."""
    return min(d, TODAY)


# =============================================================================
# 1. Business rules — ONE place. Both refund_rules.csv and the policy
#    documents are generated from these, so they can never disagree.
# =============================================================================
RETURN_WINDOW_DAYS = 30
REFUND_SLA_DAYS = 5               # refund processed within 5 days of approval
AUTO_APPROVE_LIMIT_SAR = 500      # above this, a human must approve the refund

CATEGORIES = {
    # category: (product types, price range in SAR, returnable?)
    "Protein":      (["Whey Protein", "Plant Protein", "Protein Bar Box"], (80, 350), False),
    "Vitamins":     (["Vitamin D3", "Multivitamin", "Vitamin C", "B-Complex"], (30, 150), False),
    "Pre-Workout":  (["Pre-Workout Powder", "Energy Gel Pack"], (90, 250), False),
    "Wellness":     (["Omega-3", "Collagen", "Ashwagandha", "Probiotics"], (50, 200), False),
    "Fitness Gear": (["Shaker Bottle", "Resistance Bands", "Yoga Mat", "Gym Gloves"], (20, 180), True),
    "Electronics":  (["Smart Scale", "Fitness Tracker", "Massage Gun", "Wireless Earbuds"], (150, 900), True),
}
BRANDS = ["Nuvita", "PeakForm", "Zest", "IronLeaf", "Sahara Fit", "Veda Labs"]

PAYMENT_METHODS = {
    "SA": ["card", "mada", "apple_pay", "cod"],
    "IN": ["card", "upi", "cod"],
}
CARD_LIKE = ("card", "mada", "apple_pay")   # only these can have chargebacks

SAUDI_CITIES = ["Riyadh", "Jeddah", "Dammam", "Makkah", "Madinah", "Khobar"]

# =============================================================================
# 2. Customers
# =============================================================================
def make_customer(i):
    created_at = fake_in.date_between(start_date=TODAY - timedelta(days=730),
                                      end_date=TODAY - timedelta(days=30))
    if random.random() < 0.5:
        return {"id": i, "name": fake_in.name(), "email": fake_in.email(),
                "phone": fake_in.phone_number(), "city": fake_in.city(),
                "country": "IN", "language": random.choice(["en", "hi"]),
                "created_at": created_at}
    return {"id": i, "name": fake_sa.name(), "email": fake_in.email(),
            "phone": "+9665" + str(random.randint(10000000, 99999999)),
            "city": random.choice(SAUDI_CITIES),
            "country": "SA", "language": random.choice(["ar", "en"]),
            "created_at": created_at}


customers = [make_customer(i) for i in range(1, N_CUSTOMERS + 1)]

# =============================================================================
# 3. Products (no Faker needed: our own domain rules + random)
# =============================================================================
def make_product(i):
    category = random.choice(list(CATEGORIES.keys()))
    types, (low, high), returnable = CATEGORIES[category]
    return {"id": i,
            "name": f"{random.choice(BRANDS)} {random.choice(types)}",
            "category": category,
            "price_sar": round(random.uniform(low, high), 2),
            "is_returnable": returnable}


products = [make_product(i) for i in range(1, N_PRODUCTS + 1)]

# =============================================================================
# 4. Orders and order items
# =============================================================================
STATUSES = ["delivered", "shipped", "processing", "cancelled"]
STATUS_WEIGHTS = [80, 8, 5, 7]

orders, order_items = [], []
item_id = 1

for order_id in range(1, N_ORDERS + 1):
    customer = random.choice(customers)
    ordered_at = fake_in.date_between(start_date=customer["created_at"], end_date=TODAY)
    status = random.choices(STATUSES, weights=STATUS_WEIGHTS)[0]

    delivered_at = None
    if status == "delivered":
        delivered_at = ordered_at + timedelta(days=random.randint(2, 7))
        if delivered_at > TODAY:
            status, delivered_at = "shipped", None

    total = 0
    for product in random.sample(products, k=random.randint(1, 4)):
        qty = random.randint(1, 3)
        order_items.append({"id": item_id, "order_id": order_id,
                            "product_id": product["id"], "qty": qty,
                            "unit_price_sar": product["price_sar"]})
        total += qty * product["price_sar"]
        item_id += 1

    orders.append({"id": order_id, "customer_id": customer["id"], "status": status,
                   "total_sar": round(total, 2), "ordered_at": ordered_at,
                   "delivered_at": delivered_at})

# Quick lookups ("phone books")
products_by_id = {p["id"]: p for p in products}
customers_by_id = {c["id"]: c for c in customers}
items_by_order = {}
for item in order_items:
    items_by_order.setdefault(item["order_id"], []).append(item)

# =============================================================================
# 5. Transactions (payments pack)
# =============================================================================
transactions = []
order_method = {}


def add_txn(order_id, txn_type, amount, method, created_at, status="success"):
    transactions.append({"id": len(transactions) + 1, "order_id": order_id,
                         "type": txn_type, "amount_sar": round(amount, 2),
                         "method": method, "status": status,
                         "idempotency_key": fake_in.uuid4(),
                         "created_at": cap(created_at)})


for order in orders:
    country = customers_by_id[order["customer_id"]]["country"]
    method = random.choice(PAYMENT_METHODS[country])
    order_method[order["id"]] = method

    if order["status"] == "cancelled" and method == "cod":
        continue                                   # cash never collected
    status = "pending" if method == "cod" and order["status"] != "delivered" else "success"
    add_txn(order["id"], "charge", order["total_sar"], method, order["ordered_at"], status)

    if order["status"] == "cancelled":             # prepaid but cancelled: money back
        add_txn(order["id"], "refund", order["total_sar"], method,
                order["ordered_at"] + timedelta(days=1))

# =============================================================================
# 6. Returns (commerce pack)
#    "pending" returns are left undecided ON PURPOSE: they become the refund
#    agent's test cases in January, and the rules above give the right answer.
# =============================================================================
RETURN_REASONS = ["damaged", "wrong item", "not as described",
                  "changed mind", "expired product", "late delivery"]
returns = []
delivered = [o for o in orders if o["status"] == "delivered"]

for order in random.sample(delivered, k=int(N_ORDERS * RETURN_RATE)):
    item = random.choice(items_by_order[order["id"]])
    product = products_by_id[item["product_id"]]
    requested_at = cap(order["delivered_at"] + timedelta(days=random.randint(1, 45)))
    in_window = (requested_at - order["delivered_at"]).days <= RETURN_WINDOW_DAYS

    if product["is_returnable"] and in_window:
        status = random.choices(["approved", "pending"], weights=[70, 30])[0]
    else:
        status = random.choices(["rejected", "pending"], weights=[60, 40])[0]

    refund_amount = round(item["qty"] * item["unit_price_sar"], 2)
    returns.append({"id": len(returns) + 1, "order_item_id": item["id"],
                    "reason": random.choice(RETURN_REASONS), "status": status,
                    "requested_at": requested_at,
                    "refund_amount_sar": refund_amount if status == "approved" else None})
    if status == "approved":
        add_txn(order["id"], "refund", refund_amount, order_method[order["id"]],
                requested_at + timedelta(days=random.randint(1, REFUND_SLA_DAYS)))

# =============================================================================
# 7. Chargebacks (payments pack) — only card-like payments can be charged back
# =============================================================================
CB_REASONS = ["fraud", "item_not_received", "not_as_described", "duplicate_charge"]
card_charges = [t for t in transactions if t["type"] == "charge" and t["method"] in CARD_LIKE]
chargebacks = []
for t in random.sample(card_charges, k=N_CHARGEBACKS):
    chargebacks.append({"id": len(chargebacks) + 1, "transaction_id": t["id"],
                        "reason_code": random.choice(CB_REASONS),
                        "amount_sar": t["amount_sar"],
                        "status": random.choice(["open", "won", "lost"]),
                        "opened_at": cap(t["created_at"] + timedelta(days=random.randint(10, 60)))})

# =============================================================================
# 8. Refund rules (payments pack) — generated from the business rules above
# =============================================================================
refund_rules = []
for category, (_, _, returnable) in CATEGORIES.items():
    for country, methods in PAYMENT_METHODS.items():
        for method in methods:
            refund_rules.append({
                "id": len(refund_rules) + 1,
                "category": category,
                "country": country,
                "payment_method": method,
                "returnable": returnable,
                "max_days": RETURN_WINDOW_DAYS if returnable else 0,
                "max_amount_without_approval_sar": AUTO_APPROVE_LIMIT_SAR,
                "refund_to": "bank_transfer" if method == "cod" else "original_method",
                "policy_file": "refunds.md",
            })

# =============================================================================
# 9. KYC notes (payments pack) — free text, messy on purpose, contains fake PII
# =============================================================================
KYC_TEMPLATES = [
    "ID verified via national ID upload. Address matches billing.",
    "Phone verified by OTP. ID pending.",
    "Customer called support, name on card differs from account name ({name}). Asked for ID.",
    "High order value flagged. Verified email {email} and phone {phone}.",
    "Address mismatch between billing and shipping. Shipping city {city}.",
    "Multiple failed payments last week. Monitoring.",
    "verified ok",
    "Customer refused to share ID. Limited to COD only.",
]
kyc_notes = []
for c in random.sample(customers, k=150):
    template = random.choice(KYC_TEMPLATES)
    kyc_notes.append({"id": len(kyc_notes) + 1, "customer_id": c["id"],
                      "note": template.format(**c),
                      "verified": "ID verified" in template or template == "verified ok",
                      "created_at": fake_in.date_between(start_date=c["created_at"], end_date=TODAY)})

# =============================================================================
# 10. Break things on purpose — and record every break (the eval answer key)
# =============================================================================
mess_log = []


def log_mess(table, row_id, problem):
    mess_log.append({"table": table, "row_id": row_id, "problem": problem})


# 10.1 Customers with no email
for c in random.sample(customers, k=15):
    c["email"] = ""
    log_mess("customers", c["id"], "missing email")

# 10.2 Duplicate orders: customer double-clicked "Pay", charged twice
for original in random.sample(orders, k=10):
    dup = dict(original, id=len(orders) + 1)
    orders.append(dup)
    add_txn(dup["id"], "charge", dup["total_sar"], order_method[original["id"]], dup["ordered_at"])
    log_mess("orders", dup["id"], f"duplicate of order {original['id']}, charged twice, no items")

# 10.3 Returns with no reason
for r in random.sample(returns, k=10):
    r["reason"] = ""
    log_mess("returns", r["id"], "missing reason")

# 10.4 Charge amount doesn't match order total
charges = [t for t in transactions if t["type"] == "charge"]
for t in random.sample(charges, k=5):
    t["amount_sar"] = round(t["amount_sar"] + random.choice([-10, 5, 0.5]), 2)
    log_mess("transactions", t["id"], "charge does not match order total")

# 10.5 Products with no category
for p in random.sample(products, k=5):
    p["category"] = ""
    log_mess("products", p["id"], "missing category")

# 10.6 Dates in the wrong format (keep LAST: turns dates into text)
for o in random.sample(orders, k=5):
    o["ordered_at"] = o["ordered_at"].strftime("%d/%m/%Y")
    log_mess("orders", o["id"], "ordered_at in DD/MM/YYYY format")

# =============================================================================
# 11. Policy documents (Markdown) — text built from the same business rules
# =============================================================================
non_returnable = [c for c, (_, _, r) in CATEGORIES.items() if not r]
returnable_cats = [c for c, (_, _, r) in CATEGORIES.items() if r]

POLICIES = {
    "returns.md": ("Returns Policy", "support", f"""
Customers may return eligible items within **{RETURN_WINDOW_DAYS} days of delivery**.

**Returnable categories:** {", ".join(returnable_cats)}. Items must be unused and in original packaging.

**Non-returnable categories:** {", ".join(non_returnable)}. For health and safety reasons, opened or
unopened consumable products cannot be returned, **except** when the product arrived damaged,
expired, or was the wrong item. In those cases the customer must report it within 7 days of
delivery with a photo.

Return requests after {RETURN_WINDOW_DAYS} days are rejected unless a support lead approves an exception.
"""),
    "refunds.md": ("Refunds Policy", "support, finance", f"""
Approved refunds are processed within **{REFUND_SLA_DAYS} business days**.

- Card, mada, Apple Pay and UPI payments are refunded to the **original payment method**.
- Cash on delivery (COD) orders are refunded by **bank transfer** after the customer provides account details.
- Refunds above **SAR {AUTO_APPROVE_LIMIT_SAR}** require approval by a human from the finance team.
- A refund can never exceed the amount actually paid for the item, including any discounts.
- Each refund must be issued **once only**. Duplicate refund requests for the same item are rejected.
"""),
    "shipping.md": ("Shipping Policy", "support", """
- **Saudi Arabia:** delivery in 2–4 days in Riyadh, Jeddah and Dammam; up to 7 days elsewhere.
- **India:** delivery in 3–7 days to metro cities; up to 10 days elsewhere.
- Orders not delivered within 14 days may be cancelled for a full refund.
- Cash on delivery is available in both countries, up to SAR 1,000 per order.
"""),
    "warranty.md": ("Warranty Policy", "support", """
Electronics carry a **12-month manufacturer warranty** from the date of delivery.
Fitness gear carries a **6-month warranty** against manufacturing defects.
Warranty covers repair or replacement, not refunds. Damage from misuse is not covered.
Supplements carry no warranty; quality complaints follow the returns policy exception for
damaged or expired products.
"""),
    "chargebacks.md": ("Chargeback Handling Policy", "finance, legal", """
A chargeback is a payment reversal initiated by the customer's bank.

- The finance team must respond to the bank with evidence within **7 days** of notification.
- Evidence includes: order details, delivery proof, customer communication, and refund history.
- If a refund was already issued for the same amount, respond with proof to avoid a double loss.
- Customers with **two or more chargebacks** in 12 months are restricted to COD only.
- Support agents must **not** discuss open chargebacks with customers; route to finance.
"""),
    "data_privacy.md": ("Customer Data Privacy Policy", "legal, all staff", """
Souq & Co processes personal data under Saudi Arabia's PDPL and India's DPDP Act.

- Collect only the data needed to fulfil and support orders.
- Customer email, phone, address and ID details are **confidential**. Never share them in chat
  with anyone other than the verified account holder.
- KYC notes are visible to finance and legal only, never to frontline support.
- Customer data must be stored in the customer's own region unless legal approves otherwise.
- Customers may request access to or deletion of their data; respond within 30 days.
"""),
}

for filename, (title, audience, body) in POLICIES.items():
    with open(os.path.join(POLICY_DIR, filename), "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n"
                f"**Company:** Souq & Co (fictional)  \n"
                f"**Audience:** {audience}  \n"
                f"**Version:** 1.0  \n"
                f"**Effective from:** 2025-01-01\n"
                f"{body}")

# Policy index (the "policies" table in the data model)
policy_index = [{"id": i, "file": fn, "title": t, "audience": a, "version": "1.0",
                 "effective_from": "2025-01-01"}
                for i, (fn, (t, a, _)) in enumerate(POLICIES.items(), start=1)]

# =============================================================================
# 12. Write every table
# =============================================================================
def write_csv(name, rows):
    with open(os.path.join(DATA_DIR, f"{name}.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {name:<14} {len(rows):>6} rows")


print("Souq & Co synthetic data")
for name, rows in [("customers", customers), ("products", products),
                   ("orders", orders), ("order_items", order_items),
                   ("returns", returns), ("policies", policy_index),
                   ("transactions", transactions), ("chargebacks", chargebacks),
                   ("refund_rules", refund_rules), ("kyc_notes", kyc_notes),
                   ("mess_log", mess_log)]:
    write_csv(name, rows)
print(f"  {len(POLICIES)} policy documents written to {POLICY_DIR}/")