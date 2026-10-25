"""Custom order data from the run console: template, parsing and validation.

Kept separate from the UI so it can be tested on its own. Every problem is
collected and returned, so the page can list them all at once.
"""
import csv
import io
import json
import math
import re
from datetime import date

from env.store import TODAY

COLUMNS = ["order_id", "customer", "item", "amount", "status", "delivered_on", "refunded_amount"]
STATUSES = {"processing", "shipped", "delivered", "cancelled"}
MAX_ROWS, MAX_BYTES, MAX_MESSAGE = 50, 100_000, 500
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

TEMPLATE_ROWS = [
    {"order_id": "A1", "customer": "Asha", "item": "Blender", "amount": 120, "status": "delivered",
     "delivered_on": "2026-10-20", "refunded_amount": 0},
    {"order_id": "A2", "customer": "Asha", "item": "Toaster", "amount": 60, "status": "processing",
     "delivered_on": "", "refunded_amount": 0},
    {"order_id": "B1", "customer": "Ravi", "item": "Sofa", "amount": 900, "status": "delivered",
     "delivered_on": "2026-09-01", "refunded_amount": 0},
]


def template_csv():
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(TEMPLATE_ROWS)
    return buf.getvalue()


def _blank(value):
    return value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == ""


def parse_upload(name, data):
    """CSV or JSON bytes -> (rows, errors). JSON may be a list of rows or {order_id: row}."""
    if len(data) > MAX_BYTES:
        return [], [f"File is {len(data) // 1000} KB; the limit is {MAX_BYTES // 1000} KB."]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["File is not UTF-8 text."]
    if name.lower().endswith(".json"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            return [], [f"Invalid JSON: {e}"]
        if isinstance(parsed, dict):
            parsed = [{"order_id": k, **v} for k, v in parsed.items() if isinstance(v, dict)]
        if not isinstance(parsed, list) or not all(isinstance(r, dict) for r in parsed):
            return [], ["JSON must be a list of order objects."]
        return parsed, []
    rows = list(csv.DictReader(io.StringIO(text)))
    missing = [c for c in COLUMNS if c != "refunded_amount" and rows and c not in rows[0]]
    if missing:
        return [], [f"Missing columns: {', '.join(missing)}. Use the template's header row."]
    return rows, []


def validate(rows):
    """rows -> (orders dict in store format, errors). orders is empty when there are errors."""
    errors = []
    rows = [r for r in rows if not all(_blank(v) for v in r.values())]  # ignore fully empty rows
    if not rows:
        return {}, ["Add at least one order."]
    if len(rows) > MAX_ROWS:
        return {}, [f"{len(rows)} orders; the limit is {MAX_ROWS}."]
    orders = {}
    for i, r in enumerate(rows, start=1):
        where = f"Row {i}"
        oid = "" if _blank(r.get("order_id")) else str(r["order_id"]).strip()
        if not ID_PATTERN.match(oid):
            errors.append(f"{where}: order_id is required (letters, digits, - or _).")
            continue
        where = f"Row {i} ({oid})"
        if oid in orders:
            errors.append(f"{where}: duplicate order_id.")
        customer = "" if _blank(r.get("customer")) else str(r["customer"]).strip()
        item = "" if _blank(r.get("item")) else str(r["item"]).strip()
        if not customer:
            errors.append(f"{where}: customer is required.")
        if not item:
            errors.append(f"{where}: item is required.")
        amount = _number(r.get("amount"), where, "amount", errors, required=True)
        refunded = _number(r.get("refunded_amount"), where, "refunded_amount", errors, required=False)
        if amount is not None and refunded is not None and refunded > amount:
            errors.append(f"{where}: refunded_amount is more than amount.")
        status = "" if _blank(r.get("status")) else str(r["status"]).strip().lower()
        if status not in STATUSES:
            errors.append(f"{where}: status must be one of {', '.join(sorted(STATUSES))}.")
        delivered_on = None if _blank(r.get("delivered_on")) else str(r["delivered_on"]).strip()[:10]
        if status == "delivered":
            if not delivered_on:
                errors.append(f"{where}: delivered_on is required for delivered orders.")
            else:
                try:
                    if date.fromisoformat(delivered_on) > TODAY:
                        errors.append(f"{where}: delivered_on is after today ({TODAY.isoformat()}).")
                except ValueError:
                    errors.append(f"{where}: delivered_on must be YYYY-MM-DD.")
        else:
            delivered_on = None  # only delivered orders have a delivery date
        orders[oid] = {"customer": customer, "item": item, "amount": amount or 0.0, "status": status,
                       "delivered_on": delivered_on, "refunded_amount": refunded or 0.0}
    return ({} if errors else orders), errors


def _number(value, where, field, errors, required):
    if _blank(value):
        if required:
            errors.append(f"{where}: {field} is required.")
        return None if required else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{where}: {field} must be a number.")
        return None
    if number < 0 or math.isnan(number):
        errors.append(f"{where}: {field} must be 0 or more.")
        return None
    return round(number, 2)


def validate_message(message):
    message = message.strip()
    if not message:
        return ["Write the customer's message."]
    if len(message) > MAX_MESSAGE:
        return [f"Message is {len(message)} characters; the limit is {MAX_MESSAGE}."]
    return []


def parse_expected(text, orders):
    """Optional expected changes, e.g. {"A1": {"refunded_amount": 120}} -> (dict | None, errors)."""
    if not text.strip():
        return None, []
    try:
        expected = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [f"Expected changes: invalid JSON ({e})."]
    if not isinstance(expected, dict):
        return None, ["Expected changes must be an object like {\"A1\": {\"refunded_amount\": 120}}."]
    errors = []
    for oid, change in expected.items():
        if oid not in orders:
            errors.append(f"Expected changes: order {oid} is not in your data.")
        elif not isinstance(change, dict) or not change:
            errors.append(f"Expected changes: {oid} needs fields, e.g. {{\"status\": \"cancelled\"}}.")
        else:
            for field, value in change.items():
                if field == "status" and value not in STATUSES:
                    errors.append(f"Expected changes: {oid} status must be a valid status.")
                elif field == "refunded_amount" and not isinstance(value, (int, float)):
                    errors.append(f"Expected changes: {oid} refunded_amount must be a number.")
                elif field not in ("status", "refunded_amount"):
                    errors.append(f"Expected changes: only status and refunded_amount can be checked, not {field}.")
    if errors:
        return None, errors
    return {oid: {f: (float(v) if f == "refunded_amount" else v) for f, v in ch.items()}
            for oid, ch in expected.items()}, []
