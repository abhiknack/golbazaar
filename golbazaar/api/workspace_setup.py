import frappe


def ensure_golbazaar_workspace() -> str:
	"""Create or update the Golbazaar Desk Workspace so /app/golbazaar works."""
	ws_name = "Golbazaar"
	existing = frappe.db.exists("Workspace", ws_name)
	data = {
		"doctype": "Workspace",
		"name": ws_name,
		"label": ws_name,
		"module": "Golbazaar",
		"public": 1,
		"is_hidden": 0,
		"hide_custom": 0,
		"content": "[]",
	}
	if existing:
		# update minimal fields to ensure visibility
		ws = frappe.get_doc("Workspace", ws_name)
		for k, v in data.items():
			if k != "doctype":
				setattr(ws, k, v)
		ws.save(ignore_permissions=True)
		frappe.db.commit()
		return "updated"
	# create fresh
	ws = frappe.get_doc(data)
	ws.insert(ignore_permissions=True)
	frappe.db.commit()
	return "created"


