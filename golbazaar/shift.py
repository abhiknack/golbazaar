import frappe
import time
from frappe.utils import nowdate, nowtime
from frappe.model.document import Document

# ============================================================
# SHIFT MANAGEMENT ENDPOINTS — NIBBL RETAIL API
# ============================================================

@frappe.whitelist()
def open_shift(pos_profile, user, opening_amount, company, branch, system_shift_id, posting_date=None, posting_time=None):
    """Create a POS Opening Entry (start of shift)"""
    if not posting_date or not posting_time:
        return {"error": "posting_date and posting_time are required"}
    
    # Retry logic for handling QueryDeadlockError during name generation
    max_retries = 5
    for retry in range(max_retries):
        try:
            # Check for existing shift at the start of each retry attempt
            existing = frappe.db.exists("POS Opening Entry", {
                "user": user,
                "pos_profile": pos_profile,
                "status": "Open"
            })
            if existing:
                return {"error": "Shift already open", "shift_id": existing}

            doc = frappe.get_doc({
                "doctype": "POS Opening Entry",
                "company": company,
                "pos_profile": pos_profile,
                "user": user,
                "posting_date": posting_date,
                "posting_time": posting_time,
                "opening_amount": opening_amount,
                "branch": branch,
                # Save external/system shift id into custom link field
                "gol_pos_shift_id": system_shift_id,
                "period_start_date": posting_date,  # Add required field
                "balance_details": [{                # Add required child table field
                    "mode_of_payment": "Cash",     # Use Cash or fetch dynamically if needed
                    "opening_amount": opening_amount
                }]
            })
            doc.insert(ignore_permissions=True)
            doc.submit()
            frappe.db.commit()
            return {"message": "Shift opened successfully", "shift_id": doc.name}
            
        except frappe.QueryDeadlockError as e:
            frappe.db.rollback()
            if retry < max_retries - 1:
                # Exponential backoff: wait (retry + 1) seconds before retrying
                time.sleep(retry + 1)
                continue
            else:
                # Max retries reached, raise the error
                frappe.log_error(f"QueryDeadlockError after {max_retries} retries in open_shift")
                raise
        except Exception as e:
            frappe.db.rollback()
            raise


@frappe.whitelist()
def get_active_shift(user, pos_profile):
    """Return active (open) shift for a user and profile"""
    shift = frappe.db.get_value(
        "POS Opening Entry",
        {"user": user, "pos_profile": pos_profile, "status": "Open"},
        ["name", "company", "posting_date"],  # Removed branch for schema compatibility
        as_dict=True
    )
    return {"shift": shift or None}


@frappe.whitelist()
def sync_pos_invoices(shift_id, invoices_json):
    """
    Sync offline POS invoices into ERPNext.
    invoices_json: JSON string list of invoice dicts
    """
    import json
    try:
        invoices = json.loads(invoices_json)
    except Exception:
        return {"error": "Invalid JSON"}

    synced = []
    errors = []

    for inv in invoices:
        try:
            # Check if already synced by custom_system_invoice_id
            if frappe.db.exists("POS Invoice", {"custom_system_invoice_id": inv.get("system_invoice_id")}):
                synced.append(inv.get("system_invoice_id"))
                continue
            if not inv.get("posting_date") or not inv.get("posting_time"):
                errors.append({"invoice": inv.get("system_invoice_id"), "error": "posting_date and posting_time are required"})
                continue
            doc = frappe.get_doc({
                "doctype": "POS Invoice",
                "company": inv["company"],
                "customer": inv["customer"],
                "pos_profile": inv["pos_profile"],
                "posting_date": inv["posting_date"],
                "posting_time": inv["posting_time"],
                "payments": inv.get("payments", []),
                "items": inv.get("items", []),
                "custom_system_invoice_id": inv.get("system_invoice_id"),
                "custom_system_shift_id": inv.get("system_shift_id"),
                "docstatus": 1  # Submitted
            })
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            synced.append(doc.name)
        except Exception as e:
            frappe.db.rollback()
            errors.append({"invoice": inv.get("system_invoice_id"), "error": str(e)})

    return {"synced": synced, "errors": errors}


@frappe.whitelist()
def close_shift(shift_id, closing_amount, remarks=None, period_end_date=None):
    """Close POS shift and create POS Closing Entry"""
    if not period_end_date:
        return {"error": "period_end_date is required"}
    
    # Retry logic for handling QueryDeadlockError during name generation
    max_retries = 5
    for retry in range(max_retries):
        try:
            opening = frappe.get_doc("POS Opening Entry", shift_id)
            if not opening:
                return {"error": "Shift not found"}

            if opening.status == "Closed":
                return {"error": "Shift already closed"}
            
            closing_doc = frappe.get_doc({
                "doctype": "POS Closing Entry",
                "pos_opening_entry": opening.name,
                "company": opening.company,
                "period_start_date": opening.posting_date,
                "period_end_date": period_end_date,
                "closing_amount": closing_amount,
                "remarks": remarks or "",
            })
            closing_doc.insert(ignore_permissions=True)
            closing_doc.submit()

            try:
                opening.save(ignore_permissions=True)
            except frappe.exceptions.TimestampMismatchError:
                pass
            frappe.db.commit()

            return {"message": "Shift closed successfully", "closing_entry": closing_doc.name}
            
        except frappe.QueryDeadlockError as e:
            frappe.db.rollback()
            if retry < max_retries - 1:
                # Exponential backoff: wait (retry + 1) seconds before retrying
                time.sleep(retry + 1)
                continue
            else:
                # Max retries reached, raise the error
                frappe.log_error(f"QueryDeadlockError after {max_retries} retries in close_shift")
                raise
        except Exception as e:
            frappe.db.rollback()
            raise


@frappe.whitelist(allow_guest=False)
def sync_shift_transaction(**kwargs):
    """
    Unified endpoint for POS shift events (open, close, get_active, etc).
    Usage: pass 'type': 'open', 'close', 'get_active' and relevant data.
    """
    data = frappe._dict(kwargs)
    user = frappe.session.user

    if not data.get("type"):
        frappe.throw("Missing 'type' in request. Must be one of: open, close, get_active")

    if data.type == "open":
        return open_shift(
            pos_profile=data.pos_profile,
            user=data.user,
            opening_amount=data.opening_amount,
            company=data.company,
            branch=data.branch,
            system_shift_id=data.system_shift_id,
            posting_date=data.get("posting_date"),
            posting_time=data.get("posting_time")
        )
    elif data.type == "close":
        return close_shift(
            shift_id=data.shift_id,
            closing_amount=data.closing_amount,
            remarks=data.get("remarks"),
            period_end_date=data.period_end_date,
        )
    elif data.type == "get_active":
        return get_active_shift(
            user=data.user,
            pos_profile=data.pos_profile,
        )
    else:
        frappe.throw(f"Unknown shift type: {data.type}")
