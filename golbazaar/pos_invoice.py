# File: gol_app/api/pos_sync.py

import frappe
from frappe import _
from frappe.utils import now_datetime


@frappe.whitelist(allow_guest=False)
def sync_pos_transaction(**kwargs):
    """
    Unified endpoint for POS sale and refund operations.

    Handles:
    - Normal POS Invoice creation (sale)
    - Full refund (is_return=1, full items)
    - Partial refund (is_return=1, partial items)
    - Refund only (is_return=1, update_stock=0)
    - Exchange (return + new sale)
    - Gateway refund (logs transaction reference)

    Payload Example (sale):
    {
        "type": "sale",
        "company": "Fresh Mart",
        "customer": "Walk-in Customer",
        "pos_profile": "Main Counter",
        "shift": "SHIFT-0001",
        "items": [{"item_code": "ITEM-001", "qty": 2, "rate": 100}],
        "payments": [{"mode_of_payment": "Cash", "amount": 200}],
        "posting_date": "2025-10-29",
        "posting_time": "10:30:00"
    }

    Payload Example (refund):
    {
        "type": "refund",
        "return_against": "POS-00021",
        "is_partial": 1,
        "update_stock": 1,
        "items": [{"item_code": "ITEM-001", "qty": -1, "rate": 100}],
        "payments": [{"mode_of_payment": "Cash", "amount": -100}],
        "company": "Fresh Mart"
    }

    Payload Example (exchange):
    {
        "type": "exchange",
        "return_against": "POS-00021",
        "returned_items": [{"item_code": "ITEM-001", "qty": -1, "rate": 100}],
        "new_items": [{"item_code": "ITEM-002", "qty": 1, "rate": 120}],
        "payments": [{"mode_of_payment": "UPI", "amount": 20}],
        "company": "Fresh Mart"
    }
    """

    data = frappe._dict(kwargs)
    user = frappe.session.user

    # 🧩 Validate required fields
    if not data.get("type"):
        frappe.throw("Missing 'type' in request. Must be one of: sale, refund, exchange")

    frappe.logger("pos_sync").info(f"POS sync request by {user}: {data}")

    if data.type == "sale":
        return create_pos_sale(data)

    elif data.type == "refund":
        return create_pos_refund(data)

    elif data.type == "exchange":
        return create_pos_exchange(data)

    elif data.type == "gateway_refund":
        return log_gateway_refund(data)

    else:
        frappe.throw(f"Unknown transaction type: {data.type}")


# ---------------------------------------------------------------------
# 🧾 1. POS Sale
# ---------------------------------------------------------------------
def create_pos_sale(data):
    if not data.get("posting_date") or not data.get("posting_time"):
        frappe.throw("posting_date and posting_time are required for POS Sale")
    doc = frappe.get_doc({
        "doctype": "POS Invoice",
        "company": data.company,
        "customer": data.get("customer", "Walk-in Customer"),
        "pos_profile": data.pos_profile,
        "shift": data.get("shift"),
        "posting_date": data.get("posting_date"),
        "posting_time": data.get("posting_time"),
        "is_pos": 1,
        "offline_pos_name": data.get("local_id"),
        "items": data.get("items"),
        "payments": data.get("payments"),
        "doctype": "POS Invoice"
    })
    doc.insert(ignore_permissions=True)
    doc.submit()

    return {"message": "POS Sale created", "name": doc.name, "status": doc.status}


# ---------------------------------------------------------------------
# 💰 2. POS Refund (Full / Partial / Refund Only)
# ---------------------------------------------------------------------
def create_pos_refund(data):
    if not data.get("return_against"):
        frappe.throw("return_against is required for refund")

    refund_doc = frappe.get_doc({
        "doctype": "POS Invoice",
        "is_return": 1,
        "return_against": data.get("return_against"),
        "company": data.get("company"),
        "customer": data.get("customer"),
        "update_stock": data.get("update_stock", 1),
        "items": data.get("items"),
        "payments": data.get("payments"),
        "pos_profile": data.get("pos_profile"),
        "shift": data.get("shift"),
        "remarks": data.get("remarks")
    })
    # Patch: defensively set paid_amount and grand_total to prevent None error
    payments = data.get("payments", [])
    refund_doc.paid_amount = sum(row.get("amount", 0) for row in payments) if payments else 0
    refund_doc.grand_total = abs(sum(item.get("qty", 0) * item.get("rate", 0) for item in data.get("items", [])))
    refund_doc.rounded_total = refund_doc.grand_total
    refund_doc.outstanding_amount = 0
    refund_doc.insert(ignore_permissions=True)
    refund_doc.submit()

    return {
        "message": "POS Refund created",
        "type": "full" if not data.get("is_partial") else "partial",
        "name": refund_doc.name,
        "status": refund_doc.status
    }


# ---------------------------------------------------------------------
# 🔄 3. POS Exchange (Return + New Sale)
# ---------------------------------------------------------------------
def create_pos_exchange(data):
    if not data.get("return_against"):
        frappe.throw("return_against required for exchange")

    # Create return
    return_doc = frappe.get_doc({
        "doctype": "POS Invoice",
        "is_return": 1,
        "return_against": data.return_against,
        "company": data.company,
        "items": data.get("returned_items"),
        "payments": [],
        "update_stock": 1
    }).insert(ignore_permissions=True)
    return_doc.submit()

    # Create new sale
    new_sale = frappe.get_doc({
        "doctype": "POS Invoice",
        "company": data.company,
        "items": data.get("new_items"),
        "payments": data.get("payments"),
        "is_pos": 1
    }).insert(ignore_permissions=True)
    new_sale.submit()

    return {
        "message": "Exchange completed",
        "return_invoice": return_doc.name,
        "new_invoice": new_sale.name
    }


# ---------------------------------------------------------------------
# 🧾 4. Gateway Refund Logging (no POS return)
# ---------------------------------------------------------------------
def log_gateway_refund(data):
    if not data.get("reference_date"):
        frappe.throw("reference_date is required for gateway refund log")
    ref = frappe.new_doc("Payment Entry")
    ref.update({
        "payment_type": "Pay",
        "party_type": "Customer",
        "party": data.get("customer"),
        "paid_amount": data.amount,
        "received_amount": 0,
        "mode_of_payment": data.get("mode_of_payment"),
        "reference_no": data.get("gateway_ref_no"),
        "reference_date": data.get("reference_date"),
        "company": data.company,
    })
    ref.insert(ignore_permissions=True)
    ref.submit()

    return {"message": "Gateway refund logged", "name": ref.name}
