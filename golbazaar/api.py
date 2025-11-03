import frappe

from frappe import _
from frappe.utils.password import check_password, get_decrypted_password


@frappe.whitelist(allow_guest=True)
def login_device(user_name, password, device_id):
	"""
	Authenticate user and handle device registration
	
	Parameters:
	- user_name: User's email address
	- password: User's password
	- device_id: Unique device identifier
	
	Returns:
	- {"message": {"device_id": "...", "user": "...", "companies": {...}, "api_key": "...", "api_secret": "..."}}
	"""
	try:
		# Validate credentials without relying on web request context
		check_password(user_name, password)
		
		# Clear any existing form dict noise
		# Avoid overwriting frappe.local.form_dict to preserve required attributes like 'cmd'
		
		# Check if user exists in GolPos User
		golpos_user = frappe.db.get_value("GolPos User", {"pos_user": user_name}, ["name"], as_dict=True)
		if not golpos_user:
			return {"message": {"error": "User not found in GolPos system"}}
		
		# Get all companies and their POS profiles
		companies_data = {}
		company_links = frappe.db.get_all(
			"Company Link",
			filters={"parent": golpos_user.name, "parentfield": "gpos_company"},
			fields=["linked_company"],
		)
		for link in company_links:
			if link.linked_company:
				pos_profiles = frappe.db.get_all(
					"POS Profile",
					filters={"company": link.linked_company, "disabled": 0},
					fields=["name"],
				)
				companies_data[link.linked_company] = [p.name for p in pos_profiles]
		
		# Include API keys for the provided user
		keys = get_api_keys(user_name)
		
		return {
			"message": {
				"user": user_name,
				"device_id": device_id,
				"companies": companies_data,
				"api_key": keys.get("api_key"),
				"api_secret": keys.get("api_secret"),
			}
		}
		
	except frappe.exceptions.AuthenticationError:
		frappe.local.response.http_status_code = 401
		return {"message": {"error": "Invalid credentials"}}
	except Exception as e:
		frappe.local.response.http_status_code = 500
		return {"message": {"error": str(e)}}


@frappe.whitelist()
def get_api_keys(user=None):
	"""Return (and if needed, generate) API key/secret for given user (or current)."""
	user_name = user or frappe.session.user
	user_doc = frappe.get_doc("User", user_name)
	changed = False
	
	# Ensure API Key exists
	if not user_doc.api_key:
		user_doc.api_key = frappe.generate_hash(length=15)
		changed = True
	
	# Try to read existing secret (returns decrypted value if set)
	api_secret_value = None
	try:
		api_secret_value = get_decrypted_password("User", user_doc.name, "api_secret", raise_exception=False)
	except Exception:
		api_secret_value = None
	
	# Generate secret only if missing
	if not api_secret_value:
		api_secret_value = frappe.generate_hash(length=32)
		user_doc.api_secret = api_secret_value
		changed = True
	
	if changed:
		user_doc.save(ignore_permissions=True)
	
	return {"api_key": user_doc.api_key, "api_secret": api_secret_value}


@frappe.whitelist(allow_guest=True)
def check_email(email):
	"""
	Check if an email address is available for registration
	
	Parameters:
	- email: Email address to check
	
	Returns:
	- {"message": {"not_available": true/false}}
	"""
	try:
		# Check if user exists
		exists = frappe.db.exists("User", email)
		
		return {"message": {"not_available": bool(exists)}}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Check Email Error")
		return {"message": {"not_available": False, "error": str(e)}}


@frappe.whitelist(allow_guest=True)
def lost_password(email):
	"""
	Request password reset for a user account
	
	Parameters:
	- email: Email address of the account
	
	Returns:
	- {"message": {"sent": true/false}}
	"""
	try:
		# Check if user exists
		if not frappe.db.exists("User", email):
			return {"message": {"sent": False, "error": "Email not found"}}
		
		# Generate password reset key
		user = frappe.get_doc("User", email)
		
		# Generate reset password key
		from frappe.utils import random_string
		reset_key = random_string(15)
		
		user.reset_password_key = reset_key
		user.last_reset_password_key_generated_on = frappe.utils.now()
		user.save(ignore_permissions=True)
		
		# Send reset email
		reset_link = f"{frappe.utils.get_url()}/reset-password?key={reset_key}"
		
		# Send email
		frappe.sendmail(
			recipients=[email],
			subject="Reset Your Password - TailPOS",
			message=f"""
			<p>You have requested to reset your password.</p>
			<p><a href="{reset_link}">Click here to reset your password</a></p>
			<p>Or copy this link: {reset_link}</p>
			<p>This link will expire in 24 hours.</p>
			""",
			now=True
		)
		
		return {"message": {"sent": True, "message": "Password reset email sent"}}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Lost Password Error")
		return {"message": {"sent": False, "error": str(e)}}


@frappe.whitelist(allow_guest=True)
def get_items(start=0, page_length=50, pos_profile=None, item_group=None, price_list="Standard Selling", search_term="", last_updated_time=None):
	"""
	Get items for POS
	Based on ERPNext's get_items implementation
	
	Parameters:
	- start: Pagination offset
	- page_length: Number of items per page
	- pos_profile: POS Profile name (optional)
	- item_group: Item Group name (optional)
	- price_list: Price List name (optional, default: "Standard Selling")
	- search_term: Search term for filtering items (optional)
	- last_updated_time: Only fetch items modified after this time (format: "YYYY-MM-DD HH:MM:SS")
	
	Returns:
	- {"items": [...], "total": 100, "limit": 50, "offset": 0, "has_more": true, "next_offset": 50}
	"""
	try:
		from frappe.utils import cint
		from datetime import datetime
		from erpnext.selling.page.point_of_sale.point_of_sale import (
			search_by_term,
			filter_result_items,
			get_conditions,
			get_item_group_condition,
			get_stock_availability,
			get_root_of,
			get_conversion_factor
		)
		
		# Convert to integers
		start = cint(start)
		page_length = cint(page_length)
		
		result = []
		
		# Handle incremental sync with last_updated_time
		modified_item_filters = {}
		if last_updated_time:
			try:
				last_updated_dt = datetime.strptime(last_updated_time, "%Y-%m-%d %H:%M:%S")
				modified_item_filters["modified"] = [">", last_updated_dt]
			except ValueError:
				frappe.local.response.http_status_code = 400
				return {"message": {"error": "Invalid datetime format. Use YYYY-MM-DD HH:MM:SS"}}
		
		# If last_updated_time is provided and search term is used, first get modified items
		if last_updated_time and search_term:
			modified_items = frappe.get_all("Item", fields=["name"], filters=modified_item_filters)
			modified_prices = frappe.get_all("Item Price", fields=["item_code"], 
				filters={"modified": [">", datetime.strptime(last_updated_time, "%Y-%m-%d %H:%M:%S")]})
			
			modified_item_codes = set([item["name"] for item in modified_items])
			modified_item_codes.update([p["item_code"] for p in modified_prices])
			
			if not modified_item_codes:
				return {
					"items": [],
					"total": 0,
					"limit": page_length,
					"offset": start,
					"has_more": False,
					"next_offset": None
				}
		
		# If search term provided, search by term
		if search_term:
			if not price_list:
				return {"message": {"error": "price_list is required when using search_term"}}
			
			warehouse = frappe.db.get_value("POS Profile", pos_profile, "warehouse")
			result = search_by_term(search_term, warehouse, price_list) or []
			filter_result_items(result, pos_profile)
			if result:
				return {"items": result}
		
		# Handle item group
		if item_group:
			if not frappe.db.exists("Item Group", item_group):
				item_group = get_root_of("Item Group")
		
		# Build conditions
		condition = get_conditions(search_term)
		condition += get_item_group_condition(pos_profile)
		
		# Get item group boundaries
		if item_group:
			lft, rgt = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"])
		else:
			lft, rgt = 0, 999999
		
		# Get warehouse and hide_unavailable_items from POS Profile
		hide_unavailable_items = 0
		if pos_profile:
			warehouse, hide_unavailable_items = frappe.db.get_value(
				"POS Profile", pos_profile, ["warehouse", "hide_unavailable_items"]
			)
		else:
			warehouse = None
		
		# Build bin join for stock availability
		bin_join_selection, bin_join_condition = "", ""
		if hide_unavailable_items and warehouse:
			bin_join_selection = "LEFT JOIN `tabBin` bin ON bin.item_code = item.name"
			bin_join_condition = "AND (item.is_stock_item = 0 OR (item.is_stock_item = 1 AND bin.warehouse = %(warehouse)s AND bin.actual_qty > 0))"
		
		# Build modified filter for SQL
		modified_condition = ""
		sql_params = {"warehouse": warehouse}
		if last_updated_time:
			modified_condition = "AND item.modified > %(last_updated)s"
			sql_params["last_updated"] = last_updated_dt.strftime("%Y-%m-%d %H:%M:%S")
		
		# First, get total count for pagination metadata
		total_count_data = frappe.db.sql(
			f"""
			SELECT COUNT(*) as total
			FROM `tabItem` item {bin_join_selection}
			WHERE
				item.disabled = 0
				AND item.has_variants = 0
				AND item.is_sales_item = 1
				AND item.is_fixed_asset = 0
				AND item.item_group in (SELECT name FROM `tabItem Group` WHERE lft >= {cint(lft)} AND rgt <= {cint(rgt)})
				AND {condition}
				{bin_join_condition}
				{modified_condition}
			""",
			sql_params,
			as_dict=1,
		)
		total_count = total_count_data[0]["total"] if total_count_data else 0
		
		# Fetch items with pagination
		items_data = frappe.db.sql(
			f"""
			SELECT
				item.name AS item_code,
				item.item_name,
				item.description,
				item.stock_uom,
				item.image AS item_image,
				item.is_stock_item,
				item.sales_uom,
				item.item_group,
				item.variant_of,
				item.custom_discount_type,
				item.custom_discount_value,
				item.modified
			FROM
				`tabItem` item {bin_join_selection}
			WHERE
				item.disabled = 0
				AND item.has_variants = 0
				AND item.is_sales_item = 1
				AND item.is_fixed_asset = 0
				AND item.item_group in (SELECT name FROM `tabItem Group` WHERE lft >= {cint(lft)} AND rgt <= {cint(rgt)})
				AND {condition}
				{bin_join_condition}
				{modified_condition}
			ORDER BY
				item.modified desc, item.name asc
			LIMIT
				{cint(page_length)} offset {cint(start)}
			""",
			sql_params,
			as_dict=1,
		)
		
		# If no results, return empty list with pagination metadata
		if not items_data:
			return {
				"items": result,
				"total": total_count,
				"limit": page_length,
				"offset": start,
				"has_more": False,
				"next_offset": None
			}
		
		# Get current date for price validation
		current_date = frappe.utils.today()
		
		# Process each item
		for item in items_data:
			# Get stock availability
			if warehouse:
				item.actual_qty, _ = get_stock_availability(item.item_code, warehouse)
			
			# Get item prices
			item_prices = []
			if price_list:
				item_prices = frappe.get_all(
					"Item Price",
					fields=["price_list_rate", "currency", "uom", "batch_no", "valid_from", "valid_upto"],
					filters={
						"price_list": price_list,
						"item_code": item.item_code,
						"selling": True,
						"valid_from": ["<=", current_date],
						"valid_upto": ["in", [None, "", current_date]],
					},
					order_by="valid_from desc",
				)
			
			# Get default UOM and price
			stock_uom_price = next((d for d in item_prices if d.get("uom") == item.stock_uom), {})
			item_uom = item.stock_uom
			item_uom_price = stock_uom_price
			
			# Check for sales UOM
			if item.sales_uom and item.sales_uom != item.stock_uom:
				item_uom = item.sales_uom
				sales_uom_price = next((d for d in item_prices if d.get("uom") == item.sales_uom), {})
				if sales_uom_price:
					item_uom_price = sales_uom_price
			
			# If no specific UOM price found, use first available
			if item_prices and not item_uom_price:
				item_uom = item_prices[0].get("uom")
				item_uom_price = item_prices[0]
			
			# Get conversion factor
			item_conversion_factor = get_conversion_factor(item.item_code, item_uom).get("conversion_factor")
			
			# Adjust quantity based on conversion factor
			if item.stock_uom != item_uom:
				item.actual_qty = item.actual_qty // item_conversion_factor
			
			# Adjust price based on conversion factor
			if item_uom_price and item_uom != item_uom_price.get("uom"):
				item_uom_price.price_list_rate = item_uom_price.price_list_rate * item_conversion_factor
			
			# Build result item
			row = {
				**item,
				"price_list_rate": item_uom_price.get("price_list_rate") if item_uom_price else 0,
				"currency": item_uom_price.get("currency") if item_uom_price else "",
				"uom": item_uom,
				"batch_no": item_uom_price.get("batch_no") if item_uom_price else None,
				"modified": item.modified.strftime("%Y-%m-%d %H:%M:%S") if hasattr(item, 'modified') and item.modified else None,
			}
			
			# Pack discount info using custom fields
			if item.get("custom_discount_type") and item.get("custom_discount_value"):
				row["discount"] = {
					"type": item.get("custom_discount_type"),
					"value": item.get("custom_discount_value")
				}
			
			# Remove custom discount fields from payload
			row.pop("custom_discount_type", None)
			row.pop("custom_discount_value", None)
			
			# Check if this item is a variant
			template = item.get("variant_of")
			if template:
				row["is_variant"] = True
				row["parent_name"] = template
				# Get attributes for this variant
				attrs = frappe.get_all(
					"Item Variant Attribute",
					fields=["attribute", "attribute_value as value", "numeric_values", "from_range", "to_range", "increment"],
					filters={"parent": item.item_code}
				)
				row["attributes"] = attrs
			else:
				row["is_variant"] = False
			
			result.append(row)
		
		# Attach taxes for all items in batch (Item Tax child table)
		if result:
			item_codes_batch = [r.get("item_code") for r in result]
			taxes_rows = frappe.get_all(
				"Item Tax",
				fields=[
					"parent as item_code",
					"item_tax_template",
					"tax_category",
					"valid_from",
					"minimum_net_rate",
					"maximum_net_rate",
				],
				filters={"parent": ["in", item_codes_batch]},
			)
			taxes_map = {}
			for tr in taxes_rows:
				taxes_map.setdefault(tr["item_code"], []).append({
					"item_tax_template": tr.get("item_tax_template"),
					"tax_category": tr.get("tax_category"),
					"valid_from": tr.get("valid_from"),
					"minimum_net_rate": tr.get("minimum_net_rate"),
					"maximum_net_rate": tr.get("maximum_net_rate"),
				})
			for r in result:
				code = r.get("item_code")
				if code in taxes_map:
					r["taxes"] = taxes_map[code]
		
		# Calculate pagination metadata
		has_more = (start + page_length) < total_count
		next_offset = start + page_length if has_more else None
		
		# If last_updated_time is provided, mark these items as synced by updating their modified time
		if last_updated_time and result:
			try:
				current_time = frappe.utils.now_datetime()
				item_codes = [item["item_code"] for item in result]
				
				# Update modified timestamp for synced items
				if item_codes:
					# Build safe parameter list for SQL
					placeholders = ','.join(['%s'] * len(item_codes))
					frappe.db.sql(f"""
						UPDATE `tabItem` 
						SET modified = %(modified)s 
						WHERE name IN ({placeholders})
					""", [current_time] + item_codes)
					frappe.db.commit()
			except Exception as e:
				frappe.log_error(frappe.get_traceback(), "Mark Items Synced Error")
		
		return {
			"items": result,
			"total": total_count,
			"limit": page_length,
			"offset": start,
			"has_more": has_more,
			"next_offset": next_offset
		}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Items Error")
		frappe.local.response.http_status_code = 500
		return {"message": {"error": str(e)}}


@frappe.whitelist(allow_guest=True)
def get_tax(company):
	"""
	Get all tax templates associated with a company
	
	Parameters:
	- company: Company name (required)
	
	Returns:
	- {"taxes": [...]} - List of tax templates with their details
	"""
	try:
		if not company:
			frappe.local.response.http_status_code = 400
			return {"message": {"error": "Company parameter is required"}}
		
		# Build filter for company
		filters = {"company": company}
		
		# Get all Item Tax Templates
		tax_templates = frappe.get_all(
			"Item Tax Template",
			fields=["name", "title", "company"],
			filters=filters,
			order_by="title"
		)
		
		result = []
		for template in tax_templates:
			# Get tax rates for this template
			tax_details = frappe.get_all(
				"Item Tax Template Detail",
				fields=["tax_type", "tax_rate"],
				filters={"parent": template.name},
				order_by="idx"
			)
			
			result.append({
				"name": template.name,
				"title": template.title,
				"company": template.company,
				"tax_details": tax_details
			})
		
		return {"taxes": result}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Tax Error")
		frappe.local.response.http_status_code = 500
		return {"message": {"error": str(e)}}


@frappe.whitelist(allow_guest=True)
def get_customers(start=0, page_length=50, search_term="", last_updated_time=None):
	"""
	Get customers for POS
	Similar to get_items with pagination and incremental sync
	
	Parameters:
	- start: Pagination offset (default: 0)
	- page_length: Number of customers per page (default: 50)
	- search_term: Search term for filtering customers (optional)
	- last_updated_time: Only fetch customers modified after this time (format: "YYYY-MM-DD HH:MM:SS")
	
	Returns:
	- {"customers": [...], "total": 100, "limit": 50, "offset": 0, "has_more": true, "next_offset": 50}
	"""
	try:
		from frappe.utils import cint
		from datetime import datetime
		
		# Convert to integers
		start = cint(start)
		page_length = cint(page_length)
		
		result = []
		
		# Handle incremental sync with last_updated_time
		modified_customer_filters = {}
		if last_updated_time:
			try:
				last_updated_dt = datetime.strptime(last_updated_time, "%Y-%m-%d %H:%M:%S")
				modified_customer_filters["modified"] = [">", last_updated_dt]
			except ValueError:
				frappe.local.response.http_status_code = 400
				return {"message": {"error": "Invalid datetime format. Use YYYY-MM-DD HH:MM:SS"}}
		
		# Build modified filter for SQL
		modified_condition = ""
		sql_params = {}
		if last_updated_time:
			modified_condition = "AND customer.modified > %(last_updated)s"
			sql_params["last_updated"] = last_updated_dt.strftime("%Y-%m-%d %H:%M:%S")
		
		# Build search filter
		search_condition = ""
		if search_term:
			search_condition = """AND (
				customer.customer_name LIKE %(search)s 
				OR customer.name LIKE %(search)s
				OR customer.mobile_no LIKE %(search)s
				OR customer.email_id LIKE %(search)s
			)"""
			sql_params["search"] = f"%{search_term}%"
		
		# Get total count for pagination metadata
		total_count_data = frappe.db.sql(
			f"""
			SELECT COUNT(*) as total
			FROM `tabCustomer` customer
			WHERE
				customer.disabled = 0
				{search_condition}
				{modified_condition}
			""",
			sql_params,
			as_dict=1,
		)
		total_count = total_count_data[0]["total"] if total_count_data else 0
		
		# Fetch customers with pagination
		customers_data = frappe.db.sql(
			f"""
			SELECT
				customer.name AS customer_id,
				customer.customer_name,
				customer.customer_type,
				customer.territory,
				customer.mobile_no,
				customer.email_id,
				customer.tax_id,
				customer.customer_group,
				customer.modified
			FROM
				`tabCustomer` customer
			WHERE
				customer.disabled = 0
				{search_condition}
				{modified_condition}
			ORDER BY
				customer.modified desc, customer.name asc
			LIMIT
				{cint(page_length)} offset {cint(start)}
			""",
			sql_params,
			as_dict=1,
		)
		
		# If no results, return empty list with pagination metadata
		if not customers_data:
			return {
				"customers": result,
				"total": total_count,
				"limit": page_length,
				"offset": start,
				"has_more": False,
				"next_offset": None
			}
		
		# Process each customer
		for customer in customers_data:
			# Get primary address for the customer
			addresses = frappe.db.get_all("Dynamic Link",
				filters={
					"link_doctype": "Customer",
					"link_name": customer.customer_id,
					"parenttype": "Address",
				},
				fields=["parent"],
				limit=1
			)
			
			address_data = None
			if addresses:
				address = frappe.get_doc("Address", addresses[0].parent)
				address_data = {
					"address_line1": address.address_line1,
					"address_line2": address.address_line2,
					"city": address.city,
					"state": address.state,
					"country": address.country,
					"pincode": address.pincode,
					"phone": address.phone,
					"fax": address.fax,
					"email_id": address.email_id,
				}
			
			result.append({
				"customer_id": customer.customer_id,
				"customer_name": customer.customer_name,
				"customer_type": customer.customer_type,
				"territory": customer.territory,
				"mobile_no": customer.mobile_no,
				"email_id": customer.email_id,
				"phone_no": customer.phone_no,
				"tax_id": customer.tax_id,
				"customer_group": customer.customer_group,
				"address": address_data,
				"modified": customer.modified.strftime("%Y-%m-%d %H:%M:%S") if customer.modified else None,
			})
		
		# Calculate pagination metadata
		has_more = (start + page_length) < total_count
		next_offset = start + page_length if has_more else None
		
		# If last_updated_time is provided, mark these customers as synced by updating their modified time
		if last_updated_time and result:
			try:
				current_time = frappe.utils.now_datetime()
				customer_ids = [customer["customer_id"] for customer in result]
				
				# Update modified timestamp for synced customers
				if customer_ids:
					placeholders = ','.join(['%s'] * len(customer_ids))
					frappe.db.sql(f"""
						UPDATE `tabCustomer` 
						SET modified = %(modified)s 
						WHERE name IN ({placeholders})
					""", [current_time] + customer_ids)
					frappe.db.commit()
			except Exception as e:
				frappe.log_error(frappe.get_traceback(), "Mark Customers Synced Error")
		
		return {
			"customers": result,
			"total": total_count,
			"limit": page_length,
			"offset": start,
			"has_more": has_more,
			"next_offset": next_offset
		}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Customers Error")
		frappe.local.response.http_status_code = 500
		return {"message": {"error": str(e)}}


@frappe.whitelist(allow_guest=True)
def get_pos_settings(pos_profile):
    """
    Return POS settings stored on a POS Profile.

    Parameters:
    - pos_profile: POS Profile name (required)

    Returns:
    - {"pos_settings": {...}} Only the requested "posa_" fields are returned.
    """
    try:
        if not pos_profile:
            frappe.local.response.http_status_code = 400
            return {"message": {"error": "pos_profile is required"}}

        if not frappe.db.exists("POS Profile", pos_profile):
            frappe.local.response.http_status_code = 404
            return {"message": {"error": "POS Profile not found"}}

        doc = frappe.get_doc("POS Profile", pos_profile)
        data = doc.as_dict()

        # Required POS Awesome fields
        required_fields = [
            "posa_search_limit",
            "posa_server_cache_duration",
            "posa_use_server_cache",
            "posa_local_storage",
            "posa_tax_inclusive",
            "posa_search_batch_no",
            "posa_search_serial_no",
            "posa_allow_submissions_in_background_job",

            "posa_allow_mpesa_reconcile_payments",
            "posa_allow_reconcile_payments",
            "posa_allow_make_new_payments",
            "posa_use_pos_awesome_payments",
            "posa_allow_duplicate_customer_names",
            "posa_auto_set_delivery_charges",
            "posa_use_delivery_charges",
            "posa_allow_print_draft_invoices",
            "posa_input_qty",
            "posa_new_line",
            "posa_allow_write_off_change",
            "posa_display_additional_notes",
            "posa_allow_print_last_invoice",
            "posa_allow_customer_purchase_order",
            "posa_fetch_coupon",
            "posa_hide_variants_items",
            "posa_show_template_items",
            "posa_allow_sales_order",

            "posa_allow_zero_rated_items",
            "posa_display_item_code",
            "posa_auto_set_batch",
            "posa_hide_closing_shift",
            "posa_apply_customer_discount",
            "posa_allow_return",
            "posa_allow_credit_sale",
            "posa_allow_partial_payment",
            "posa_display_items_in_stock",
            "posa_allow_user_to_edit_item_discount",

            "posa_default_sales_order",
            "posa_default_card_view",
            "posa_allow_change_posting_date",
            "posa_scale_barcode_start",
            "posa_max_discount_allowed",
            "posa_use_percentage_discount",
            "posa_allow_user_to_edit_additional_discount",
            "posa_allow_user_to_edit_rate",
            "posa_allow_delete",
            "posa_cash_mode_of_payment",
            # Add new required field for variant display inside item
            "gol_show_variant_inside_item",
        ]

        # Map fields to requested response keys
        key_map = {
            "posa_search_limit": "search_limit_number",
            "posa_server_cache_duration": "server_cache_duration",
            "posa_use_server_cache": "use_server_cache",
            "posa_local_storage": "use_browser_local_storage",
            "posa_tax_inclusive": "tax_inclusive",
            "posa_search_batch_no": "search_by_batch_number",
            "posa_search_serial_no": "search_by_serial_number",
            "posa_allow_submissions_in_background_job": "allow_submissions_in_background_job",

            "posa_allow_mpesa_reconcile_payments": "allow_mpesa_reconcile_payments",
            "posa_allow_reconcile_payments": "allow_reconcile_payments",
            "posa_allow_make_new_payments": "allow_make_new_payments",
            "posa_use_pos_awesome_payments": "use_gol_bazaar_payments",
            "posa_allow_duplicate_customer_names": "allow_duplicate_customer_names",
            "posa_auto_set_delivery_charges": "auto_set_delivery_charges",
            "posa_use_delivery_charges": "use_delivery_charges",
            "posa_allow_print_draft_invoices": "allow_print_draft_invoices",
            "posa_input_qty": "use_qty_input",
            "posa_new_line": "allow_add_new_items_on_new_line",
            "posa_allow_write_off_change": "allow_write_off_change",
            "posa_display_additional_notes": "display_additional_notes",
            "posa_allow_print_last_invoice": "allow_print_last_invoice",
            "posa_allow_customer_purchase_order": "allow_customer_purchase_order",
            "posa_fetch_coupon": "auto_fetch_coupon_gifts",
            "posa_hide_variants_items": "hide_variants_items",
            "posa_show_template_items": "show_template_items",
            "posa_allow_sales_order": "allow_create_sales_order",

            "posa_allow_zero_rated_items": "allow_zero_rated_items",
            "posa_display_item_code": "display_item_code",
            "posa_auto_set_batch": "auto_set_batch",
            "posa_hide_closing_shift": "hide_close_shift",
            "posa_apply_customer_discount": "apply_customer_discount",
            "posa_allow_return": "allow_return",
            "posa_allow_credit_sale": "allow_credit_sale",
            "posa_allow_partial_payment": "allow_partial_payment",
            "posa_display_items_in_stock": "hide_unavailable_items",
            "posa_allow_user_to_edit_item_discount": "allow_user_to_edit_item_discount",

            "posa_default_sales_order": "default_sales_order",
            "posa_default_card_view": "default_card_view",
            "posa_allow_change_posting_date": "allow_change_posting_date",
            "posa_scale_barcode_start": "scale_barcode_start_with",
            "posa_max_discount_allowed": "max_discount_percentage_allowed",
            "posa_use_percentage_discount": "use_percentage_discount",
            "posa_allow_user_to_edit_additional_discount": "allow_user_to_edit_additional_discount",
            "posa_allow_user_to_edit_rate": "allow_user_to_edit_rate",
            "posa_allow_delete": "auto_delete_draft_invoice",
            "posa_cash_mode_of_payment": "cash_mode_of_payment",
            # Map the new field to the output response
            "gol_show_variant_inside_item": "show_variant_inside_item",
        }

        # Build response: keys are the provided labels
        pos_settings = { key_map[f]: data.get(f) for f in required_fields if f in key_map }

        return {"pos_settings": pos_settings, "pos_profile": pos_profile}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get POS Settings Error")
        frappe.local.response.http_status_code = 500
        return {"message": {"error": str(e)}}
