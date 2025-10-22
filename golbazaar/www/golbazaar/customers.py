import frappe


def get_context(context):
	context.customers = frappe.get_all(
		"Customer",
		fields=["name", "customer_name", "customer_group", "territory", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)
	return context


