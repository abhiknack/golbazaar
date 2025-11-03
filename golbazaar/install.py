import frappe


def after_install():
    """After installing golbazaar, hide unrelated Workspaces by default.

    Keeps:
    - Workspaces whose module is 'Golbazaar' (best-effort, module may be empty on some versions)
    - Any names listed in site config under 'golbazaar_keep_workspaces' (list of names)
    """
    keep = set()

    # Keep workspaces explicitly configured in site config
    try:
        configured = frappe.get_site_config().get("golbazaar_keep_workspaces") or []
        if isinstance(configured, (list, tuple)):
            keep.update(configured)
    except Exception:
        pass

    # Keep workspaces belonging to our module if module field exists
    try:
        gb_ws = frappe.get_all("Workspace", filters={"module": "Golbazaar"}, pluck="name")
        keep.update(gb_ws)
    except Exception:
        # Some versions may not have module or may error; ignore
        pass

    # If no explicit keep list detected, keep none by default
    all_ws = frappe.get_all("Workspace", pluck="name")
    for name in all_ws:
        if name in keep:
            continue
        try:
            # Unpublish/hide
            if frappe.db.has_column("Workspace", "public"):
                frappe.db.set_value("Workspace", name, "public", 0)
            elif frappe.db.has_column("Workspace", "is_published"):
                frappe.db.set_value("Workspace", name, "is_published", 0)
        except Exception:
            # best-effort; continue with others
            continue

    try:
        frappe.clear_cache(doctype="Workspace")
    except Exception:
        frappe.clear_cache()
