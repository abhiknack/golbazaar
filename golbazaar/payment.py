import frappe


@frappe.whitelist(allow_guest=False)
def get_payment_methods(company: str | None = None, only_enabled: bool = True):
    """
    Return available payment methods (Mode of Payment), optionally filtered by company.
    Returns only enabled payment methods by default as an array of names.
    - company: if provided, include only methods that have an account for the company
    - only_enabled: if True, filter by enabled/disabled field when available
    """
    try:
        mop_meta = frappe.get_meta("Mode of Payment")
        has_enabled = any(df.fieldname == "enabled" for df in mop_meta.fields)
        has_disabled = any(df.fieldname == "disabled" for df in mop_meta.fields)

        filters = []
        if only_enabled:
            if has_enabled:
                filters.append(["Mode of Payment", "enabled", "=", 1])
            elif has_disabled:
                filters.append(["Mode of Payment", "disabled", "=", 0])

        fields = ["name"]
        methods = frappe.db.get_list(
            "Mode of Payment",
            filters=filters or None,
            fields=fields,
            order_by="name asc",
            as_list=False,
        )

        if company:
            # Filter methods to those having an account row for the given company
            allowed_names = set(
                r.parent
                for r in frappe.db.get_all(
                    "Mode of Payment Account",
                    filters={"company": company},
                    fields=["parent"],
                    as_list=False,
                )
            )
            methods = [m for m in methods if m.get("name") in allowed_names]

        # Return array of names only
        result = [m.get("name") for m in methods if m.get("name")]
        return result
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False)
def get_payment_gateways(only_enabled: bool = True):
    """
    Return available payment gateways (Payment Gateway DocType) when present.
    Returns only enabled payment gateways by default as an array of names.
    - only_enabled: if True, filter by enabled/disabled field when available
    """
    try:
        if not frappe.db.exists("DocType", "Payment Gateway"):
            return []

        pg_meta = frappe.get_meta("Payment Gateway")
        has_enabled = any(df.fieldname == "enabled" for df in pg_meta.fields)
        has_disabled = any(df.fieldname == "disabled" for df in pg_meta.fields)

        filters = []
        if only_enabled:
            if has_enabled:
                filters.append(["Payment Gateway", "enabled", "=", 1])
            elif has_disabled:
                filters.append(["Payment Gateway", "disabled", "=", 0])

        fields = ["name"]
        gateways = frappe.db.get_list(
            "Payment Gateway",
            filters=filters or None,
            fields=fields,
            order_by="name asc",
            as_list=False,
        )

        # Return array of names only
        result = [g.get("name") for g in gateways if g.get("name")]
        return result
    except Exception as e:
        return {"error": str(e)}



