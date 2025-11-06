# File: gol_app/api/pos_sync.py

import frappe
from frappe import _
from frappe.utils import now_datetime, flt


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
    
    # Process items to ensure discounts are applied correctly
    items = data.get("items") or []
    for item in items:
        # Compute effective rate locally to avoid ERPNext ignoring discount fields in some setups
        if item.get("rate") is not None and (item.get("discount_amount") is not None or item.get("discount_percentage") is not None):
            base_rate = flt(item.get("rate", 0))
            if item.get("discount_amount") is not None:
                effective_rate = base_rate - flt(item.get("discount_amount", 0))
            elif item.get("discount_percentage") is not None:
                pct = flt(item.get("discount_percentage", 0))
                effective_rate = base_rate * (1.0 - pct / 100.0)
            else:
                effective_rate = base_rate

            # Ensure non-negative and round to 2 decimals
            item["rate"] = round(max(effective_rate, 0), 2)

            # Remove discount fields to prevent double-discounting by ERPNext
            item.pop("discount_amount", None)
            item.pop("discount_percentage", None)
    
    # Ensure payment.account is set from Mode of Payment defaults (cache lookups)
    payments = data.get("payments") or []
    account_cache = {}
    if payments:
        try:
            from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account
            for row in payments:
                if row and not row.get("account") and row.get("mode_of_payment"):
                    mop = row.get("mode_of_payment")
                    # Cache account lookups to avoid repeated calls
                    if mop not in account_cache:
                        acc = get_bank_cash_account(mop, data.company)
                        account_cache[mop] = acc.get("account") if acc else None
                    if account_cache[mop]:
                        row["account"] = account_cache[mop]
        except Exception:
            pass
    
    # Build document fields efficiently
    doc_fields = {
        "doctype": "POS Invoice",
        "company": data.company,
        "customer": data.get("customer", "Walk-in Customer"),
        "pos_profile": data.pos_profile,
        "shift": data.get("shift"),
        "posting_date": data.get("posting_date"),
        "posting_time": data.get("posting_time"),
        "is_pos": 1,
        "offline_pos_name": data.get("local_id"),
        "gol_unique_id": data.get("client_reference_id"),
        "items": items,
        "payments": payments,
    }
    
    # Conditionally add optional fields (consolidated)
    if "included_in_print_rate" in data:
        doc_fields["included_in_print_rate"] = int(data.get("included_in_print_rate", 0))
    
    optional_fields = {
        "additional_discount_percentage": float,
        "discount_amount": float,  # Invoice-level
        "rounded_total": float,
        "net_total": float,
        "base_net_total": float,
    }
    
    for field, converter in optional_fields.items():
        if field in data and data[field] is not None:
            try:
                doc_fields[field] = converter(data[field])
            except (ValueError, TypeError):
                pass  # Skip invalid values
    
    # Handle apply_discount_on with validation
    if data.get("apply_discount_on"):
        apply_on = data.get("apply_discount_on")
        doc_fields["apply_discount_on"] = apply_on if apply_on in ["Grand Total", "Net Total"] else "Grand Total"
    
    doc = frappe.get_doc(doc_fields)
    doc.insert(ignore_permissions=True)
    
    # Verify and fix item rates if discounts weren't applied correctly
    # This can happen if ERPNext didn't calculate rates from price_list_rate - discount_amount
    for item in doc.items:
        if item.discount_amount and item.price_list_rate:
            expected_rate = item.price_list_rate - item.discount_amount
            # If rate doesn't match expected, fix it
            if abs(item.rate - expected_rate) > 0.01:
                item.rate = expected_rate
        elif item.discount_percentage and item.price_list_rate:
            expected_rate = item.price_list_rate * (1.0 - item.discount_percentage / 100.0)
            if abs(item.rate - expected_rate) > 0.01:
                item.rate = expected_rate
    
    # Recalculate totals after fixing item rates
    doc.calculate_taxes_and_totals()
    
    # Ensure taxes are applied correctly based on included_in_print_rate and item_tax_template
    # If item_tax_template is provided, ensure taxes are set from the template
    has_item_tax_template = any(item.get("item_tax_template") for item in doc.items)
    if has_item_tax_template:
        # Collect unique tax types from all item tax templates
        tax_map = {}  # tax_type -> {rate, account_head, description}
        
        for item in doc.items:
            if item.item_tax_template:
                # Get tax details from Item Tax Template
                tax_details = frappe.get_all(
                    "Item Tax Template Detail",
                    filters={"parent": item.item_tax_template},
                    fields=["tax_type", "tax_rate"],
                    order_by="idx"
                )
                
                for tax_detail in tax_details:
                    tax_type = tax_detail.tax_type  # tax_type is already the Account name
                    if tax_type not in tax_map:
                        tax_map[tax_type] = {
                            "rate": tax_detail.tax_rate,
                            "account_head": tax_type,  # tax_type is the account name
                            "description": tax_type.split("-")[0].strip() if "-" in tax_type else tax_type
                        }
        
        # Add taxes to document if they don't exist
        if tax_map:
            existing_tax_accounts = {tax.account_head for tax in doc.get("taxes") or []}
            
            for tax_type, tax_data in tax_map.items():
                if tax_data["account_head"] not in existing_tax_accounts:
                    doc.append("taxes", {
                        "charge_type": "On Net Total",
                        "account_head": tax_data["account_head"],
                        "rate": tax_data["rate"],
                        "description": tax_data["description"],
                        "included_in_print_rate": 1 if doc.included_in_print_rate else 0
                    })
            
            # Recalculate taxes after adding tax rows
            doc.calculate_taxes_and_totals()
    
    # If tax is inclusive (included_in_print_rate = 1), ensure tax rows also have it set
    # and net_rate is calculated correctly
    if doc.included_in_print_rate:
        # Set included_in_print_rate on all tax rows to match document setting
        for tax in doc.get("taxes") or []:
            if not tax.get("included_in_print_rate"):
                tax.included_in_print_rate = 1
        
        # Recalculate to ensure tax-inclusive pricing is handled correctly
        # ERPNext extracts tax-exclusive amount (net_rate) from tax-inclusive amount (rate)
        doc.calculate_taxes_and_totals()
    
    # Final recalculation to ensure everything is correct
    doc.calculate_taxes_and_totals()
    
    # Adjust payment total to match grand_total (after ALL taxes/discounts calculated)
    # This must happen after all tax calculations to ensure payment matches final total
    invoice_total = flt(doc.rounded_total) or flt(doc.grand_total) or 0
    payment_total = sum(flt(p.get("amount", 0)) for p in doc.payments)
    
    if abs(payment_total - invoice_total) > 0.01:
        if doc.payments:
            # Adjust first payment to cover the difference
            difference = invoice_total - payment_total
            doc.payments[0].amount = flt(doc.payments[0].amount) + flt(difference)
            
            # Recalculate paid_amount from payments table
            payment_total = sum(flt(p.get("amount", 0)) for p in doc.payments)
            
            # Set paid_amount to match invoice total exactly
            doc.paid_amount = invoice_total
            doc.outstanding_amount = 0
            
            # Set base amounts
            base_invoice_total = flt(doc.base_rounded_total) or flt(doc.base_grand_total) or 0
            doc.base_paid_amount = base_invoice_total
            doc.base_outstanding_amount = 0
        else:
            frappe.throw("Payment amount mismatch: invoice_total={}, payment_total={}, grand_total={}, rounded_total={}".format(
                invoice_total, payment_total, doc.grand_total, doc.rounded_total))
    
    # Final check: ensure paid_amount matches exactly
    if abs(doc.paid_amount - invoice_total) > 0.01:
        doc.paid_amount = invoice_total
        doc.outstanding_amount = 0
        base_invoice_total = flt(doc.base_rounded_total) or flt(doc.base_grand_total) or 0
        doc.base_paid_amount = base_invoice_total
        doc.base_outstanding_amount = 0
    
    # Save before submit to ensure all changes (taxes, payments) are persisted
    doc.save(ignore_permissions=True)
    
    # Reload to ensure all fields are in sync
    doc.reload()
    
    # Final validation before submit
    final_invoice_total = flt(doc.rounded_total) or flt(doc.grand_total) or 0
    final_payment_total = sum(flt(p.get("amount", 0)) for p in doc.payments)
    
    if abs(final_payment_total - final_invoice_total) > 0.01:
        # Last attempt: adjust payment one more time
        if doc.payments:
            diff = final_invoice_total - final_payment_total
            doc.payments[0].amount = flt(doc.payments[0].amount) + flt(diff)
            doc.paid_amount = final_invoice_total
            doc.outstanding_amount = 0
            doc.save(ignore_permissions=True)
    
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
