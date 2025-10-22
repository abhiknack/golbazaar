import frappe


def get_context(context):
	context.suppliers = frappe.get_all(
		"Supplier",
		fields=["name", "supplier_name", "supplier_group", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)
	return context


