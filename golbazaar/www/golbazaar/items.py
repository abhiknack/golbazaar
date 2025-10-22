import frappe


def get_context(context):
	context.items = frappe.get_all(
		"Item",
		fields=["name", "item_name", "item_group", "stock_uom", "disabled", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)
	return context


