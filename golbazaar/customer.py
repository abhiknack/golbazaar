import frappe
from frappe import _


def _get_available_name(base_name: str) -> str:
    """Return a unique customer name by appending (2), (3), ... if needed.
    Optimized to compute next suffix using a single SQL query instead of looping.
    """
    # Quick path: if exact base doesn't exist, use it
    if not frappe.db.exists("Customer", base_name):
        return base_name

    # Compute maximum numeric suffix for names matching: base_name (N)
    # Example: for base_name = 'john', match 'john (2)', 'john (3)', ...
    # Extract N using SUBSTRING/LOCATE and cast to UNSIGNED, then take MAX
    like_pattern = f"{base_name} (%"
    sql = f"""
        SELECT COALESCE(MAX(CAST(
            SUBSTRING(
                name,
                LOCATE('(', name) + 1,
                LOCATE(')', name) - LOCATE('(', name) - 1
            ) AS UNSIGNED
        )), 1) AS max_suffix
        FROM `tabCustomer`
        WHERE name LIKE %s AND name REGEXP %s
    """
    # REGEXP to ensure we only consider names like: base_name (number)
    regexp_pattern = f"^{frappe.db.escape_string(base_name).decode() if hasattr(frappe.db, 'escape_string') else base_name} \\([0-9]+\\)$"
    try:
        res = frappe.db.sql(sql, (like_pattern, regexp_pattern))
        max_suffix = res[0][0] if res and res[0] and res[0][0] else 1
        next_suffix = int(max_suffix) + 1
    except Exception:
        # Fallback to iterative approach if SQL fails for any reason
        next_suffix = 2
        while frappe.db.exists("Customer", f"{base_name} ({next_suffix})"):
            next_suffix += 1

    return f"{base_name} ({next_suffix})"

@frappe.whitelist(allow_guest=False)
def create_customer(customer_name, company, customer_group=None, territory=None, price_list=None, currency=None, mobile_no=None, email_id=None, auto_suffix_duplicate: bool=True):
    """
    Create a new Customer. Returns JSON with customer name or error.
    Required: customer_name, company. Others use defaults if not provided.
    Optional: mobile_no, email_id (validated if provided).
    If auto_suffix_duplicate=True, will create as "Name (2)", "Name (3)", ... on conflicts.
    """
    import re
    # Hardcoded defaults
    customer_group = customer_group or "Individual"
    territory = territory or "All Territories"
    price_list = price_list or "Standard Selling"
    currency = currency or "INR"

    if not (customer_name and company):
        return {"error": "Missing required fields"}
    if mobile_no:
        mobile = str(mobile_no)
        if not mobile.isdigit() or not (7 <= len(mobile) <= 15):
            return {"error": "Invalid mobile_no. It should be 7-15 digits."}
    if email_id:
        email = str(email_id)
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return {"error": "Invalid email_id format."}

    try:
        # Ensure unique name if requested
        target_name = customer_name
        if frappe.db.exists("Customer", target_name):
            if auto_suffix_duplicate:
                target_name = _get_available_name(target_name)
            else:
                return {"error": _("Customer '{0}' already exists").format(customer_name)}

        doc_fields = {
            "doctype": "Customer",
            "customer_name": target_name,
            "customer_group": customer_group,
            "territory": territory,
            "default_price_list": price_list,
            "default_currency": currency,
            "customer_type": "Individual",
            # Store provided company into new link field
            "gol_customer_company": company
        }
        if mobile_no:
            doc_fields["mobile_no"] = mobile_no
        if email_id:
            doc_fields["email_id"] = email_id
        doc = frappe.get_doc(doc_fields)
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return {"message": "Customer created", "customer": doc.name}
    except Exception as e:
        frappe.db.rollback()
        return {"error": str(e)}

@frappe.whitelist(allow_guest=False)
def edit_customer(customer_name, **fields):
    """
    Edit an existing Customer.
    Pass field=value as kwargs. If new_name is provided, will rename the doc.
    Common fields: mobile_no, email_id, customer_name, plus any DocType field.
    Supports auto_suffix_duplicate when renaming.
    """
    import re
    if not customer_name:
        return {"error": "customer_name required"}
    # Validation for common fields
    if "mobile_no" in fields:
        mobile = str(fields["mobile_no"])
        if not mobile.isdigit() or not (7 <= len(mobile) <= 15):
            return {"error": "Invalid mobile_no. It should be 7-15 digits."}
    if "email_id" in fields:
        email = str(fields["email_id"])
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return {"error": "Invalid email_id format."}

    try:
        doc = frappe.get_doc("Customer", customer_name)
        auto_suffix_duplicate = fields.pop("auto_suffix_duplicate", True)
        new_name = fields.pop("new_name", None)
        # Map incoming 'company' to the new link field
        if "company" in fields and "gol_customer_company" not in fields:
            fields["gol_customer_company"] = fields.pop("company")
        for k, v in fields.items():
            if hasattr(doc, k):
                setattr(doc, k, v)
            else:
                doc.set(k, v)
        doc.save(ignore_permissions=True)
        if new_name:
            target = new_name
            if frappe.db.exists("Customer", target):
                if auto_suffix_duplicate:
                    target = _get_available_name(target)
                else:
                    return {"error": _("Customer '{0}' already exists").format(new_name)}
            frappe.rename_doc("Customer", doc.name, target)
            doc = frappe.get_doc("Customer", target)  # reload doc after rename
        frappe.db.commit()
        return {"message": "Customer updated", "customer": doc.name}
    except Exception as e:
        frappe.db.rollback()
        return {"error": str(e)}

@frappe.whitelist(allow_guest=False)
def delete_customer(customer_name):
    """Delete a customer by name"""
    if not customer_name:
        return {"error": "customer_name required"}
    try:
        frappe.delete_doc("Customer", customer_name, ignore_permissions=True)
        frappe.db.commit()
        return {"message": "Customer deleted", "customer": customer_name}
    except Exception as e:
        frappe.db.rollback()
        return {"error": str(e)}

@frappe.whitelist(allow_guest=False)
def get_customers(page: int = 1, page_size: int = 20, search: str | None = None, company: str | None = None, order_by: str = "modified desc"):
    """Return customers in a paginated way with optional search and company filter.
    - page: 1-based page number
    - page_size: items per page (max 200 recommended)
    - search: matches against name and customer_name (LIKE)
    - company: filter by company if provided
    - order_by: SQL order by (safe columns)
    """
    page = int(page or 1)
    page_size = int(page_size or 20)
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20

    # Build raw SQL to avoid framework adding permission conditions that refer to a non-existent 'company' column
    conditions = []
    params = []
    if company:
        # Filter by gol_customer_company when provided
        meta = frappe.get_meta("Customer")
        if meta.has_field("gol_customer_company"):
            conditions.append("gol_customer_company = %s")
            params.append(company)
    if search:
        conditions.append("(name like %s or customer_name like %s)")
        like = f"%{search}%"
        params.extend([like, like])

    where_sql = f" where {' and '.join(conditions)}" if conditions else ""
    start = (page - 1) * page_size

    # very small whitelist for order_by to prevent SQL injection
    allowed_order_fields = {"modified", "name", "customer_name"}
    try:
        ob_field, ob_dir = order_by.split()
        if ob_field not in allowed_order_fields or ob_dir.lower() not in {"asc", "desc"}:
            order_clause = " order by modified desc"
        else:
            order_clause = f" order by {ob_field} {ob_dir}"
    except Exception:
        order_clause = " order by modified desc"

    total = frappe.db.sql(f"select count(*) from `tabCustomer`{where_sql}", params)[0][0]
    rows = frappe.db.sql(
        f"""
        select name, customer_name, mobile_no, email_id, gol_customer_company, customer_group,
               territory, default_price_list, default_currency, modified
        from `tabCustomer`
        {where_sql}
        {order_clause}
        limit %s offset %s
        """,
        params + [page_size, start],
        as_dict=True,
    )
    items = rows

    # Rename gol_customer_company -> company in response for consumers
    for it in items:
        if "gol_customer_company" in it:
            it["company"] = it.pop("gol_customer_company")

    has_next = (start + len(items)) < total
    next_page = page + 1 if has_next else None

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_next": has_next,
        "next_page": next_page,
    }

@frappe.whitelist(allow_guest=False)
def sync_customer_transaction(**kwargs):
    """
    Unified endpoint for customer operations: create, edit, delete.
    Usage: type='create', 'edit', or 'delete' and pass required fields for each.
    """
    data = frappe._dict(kwargs)
    if not data.get("type"):
        frappe.throw("Missing 'type' in request. Must be one of: create, edit, delete")

    if data.type == "create":
        return create_customer(
            customer_name=data.get("customer_name"),
            company=data.get("company"),
            customer_group=data.get("customer_group"),
            territory=data.get("territory"),
            price_list=data.get("price_list"),
            currency=data.get("currency"),
            mobile_no=data.get("mobile_no"),
            email_id=data.get("email_id"),
            auto_suffix_duplicate=bool(data.get("auto_suffix_duplicate", True))
        )
    elif data.type == "edit":
        customer_name = data.pop("customer_name", None)
        if not customer_name:
            frappe.throw("customer_name required for edit type")
        fields = {k: v for k, v in data.items() if k not in ("type", "customer_name")}
        if "auto_suffix_duplicate" not in fields:
            fields["auto_suffix_duplicate"] = True
        return edit_customer(customer_name, **fields)
    elif data.type == "delete":
        customer_name = data.get("customer_name")
        if not customer_name:
            frappe.throw("customer_name required for delete type")
        return delete_customer(customer_name)
    elif data.type == "list":
        return get_customers(
            page=data.get("page", 1),
            page_size=data.get("page_size", 20),
            search=data.get("search"),
            company=data.get("company"),
            order_by=data.get("order_by", "modified desc"),
        )
    else:
        frappe.throw(f"Unknown customer transaction type: {data.type}")
