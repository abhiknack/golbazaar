import frappe


def get_context(context):
	context.sales_invoices = frappe.get_all(
		"Sales Invoice",
		fields=["name", "customer", "posting_date", "grand_total", "status", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)
	return context


