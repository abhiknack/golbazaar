import frappe


def execute():
	ws_name = "Golbazaar"
	if frappe.db.exists("Workspace", ws_name):
		ws = frappe.get_doc("Workspace", ws_name)
		ws.title = ws.title or ws_name
		ws.public = 1
		ws.is_hidden = 0
		ws.module = "Golbazaar"
		ws.save(ignore_permissions=True)
		return
	ws = frappe.get_doc({
		"doctype": "Workspace",
		"name": ws_name,
		"label": ws_name,
		"title": ws_name,
		"module": "Golbazaar",
		"public": 1,
		"is_hidden": 0,
		"hide_custom": 0,
		"content": "[]",
	})
	ws.insert(ignore_permissions=True)
	frappe.db.commit()


