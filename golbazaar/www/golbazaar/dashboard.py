import frappe


def get_context(context):
	context.title = "Golbazaar Dashboard"
	context.app_name = "golbazaar"

	# Basic stats
	context.total_users = frappe.db.count("User")
	context.total_doctypes = frappe.db.count("DocType")

	# Latest Items for web dashboard
	try:
		items = frappe.get_list(
			"Item",
			fields=["name", "item_name", "item_group", "stock_uom", "disabled"],
			order_by="modified desc",
			limit_page_length=10,
			ignore_permissions=True,
		)
	except Exception:
		items = []
	context.items = items

	context.recent_activities = [
		{"title": "Golbazaar Web Dashboard", "time": "Just now", "type": "success"},
	]

	return context


