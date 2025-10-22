import frappe
from frappe import _
from frappe.utils import flt, cint, cstr
import json


@frappe.whitelist()
def get_latest_items(limit: int = 10):
	"""Return latest Items for Desk Vue page."""
	limit = int(limit) if limit else 10
	return frappe.get_list(
		"Item",
		fields=["name", "item_name", "item_group", "stock_uom", "disabled", "modified"],
		order_by="modified desc",
		limit_page_length=limit,
		ignore_permissions=True,
	)


@frappe.whitelist(allow_guest=True)
def get_pos_items(filters=None, fields=None, limit=50, offset=0, search_term=None):
	"""
	Get items for POS with essential fields only.
	Returns minimal payload optimized for POS operations.
	"""
	try:
		# Parse filters if provided as JSON string
		if isinstance(filters, str):
			filters = json.loads(filters)
		if isinstance(fields, str):
			fields = json.loads(fields)
		
		# Default filters for POS
		default_filters = {
			"is_sales_item": 1,
			"disabled": 0
		}
		
		# Merge with provided filters
		if filters:
			default_filters.update(filters)
		
		# Default fields for POS (minimal payload)
		default_fields = [
			"item_code", "item_name", "item_group", "stock_uom", "standard_rate",
			"is_sales_item", "disabled", "image", "brand", "description",
			"has_variants", "variant_of", "is_stock_item", "grant_commission",
			"max_discount", "valuation_rate"
		]
		
		# Use provided fields or defaults
		fields_to_fetch = fields if fields else default_fields
		
		# Add search functionality
		or_filters = []
		if search_term:
			search_term = cstr(search_term).strip()
			or_filters = [
				["item_name", "like", f"%{search_term}%"],
				["item_code", "like", f"%{search_term}%"],
				["description", "like", f"%{search_term}%"]
			]
		
		# Get items
		items = frappe.get_list(
			"Item",
			fields=fields_to_fetch,
			filters=default_filters,
			or_filters=or_filters,
			limit_page_length=cint(limit),
			limit_start=cint(offset),
			order_by="item_name asc",
			ignore_permissions=True
		)
		
		# Get total count for pagination
		total_count = frappe.db.count("Item", default_filters)
		
		# Enhance items with related data
		enhanced_items = []
		for item in items:
			enhanced_item = enhance_pos_item(item)
			enhanced_items.append(enhanced_item)
		
		return {
			"success": True,
			"items": enhanced_items,
			"total_count": total_count,
			"has_more": (cint(offset) + len(items)) < total_count,
			"limit": cint(limit),
			"offset": cint(offset)
		}
		
	except Exception as e:
		frappe.log_error(f"Error in get_pos_items: {str(e)}")
		return {
			"success": False,
			"error": str(e),
			"items": [],
			"total_count": 0
		}


@frappe.whitelist(allow_guest=True)
def get_pos_item_by_code(item_code):
	"""Get single POS item by item code with all related data."""
	try:
		item = frappe.get_doc("Item", item_code)
		if not item:
			return {"success": False, "error": "Item not found"}
		
		enhanced_item = enhance_pos_item(item.as_dict())
		return {
			"success": True,
			"item": enhanced_item
		}
		
	except Exception as e:
		return {
			"success": False,
			"error": str(e)
		}


@frappe.whitelist(allow_guest=True)
def search_pos_items(query, limit=20):
	"""Search items for POS with barcode, customer code, and text search."""
	try:
		query = cstr(query).strip()
		if not query:
			return {"success": False, "error": "Empty search query"}
		
		results = []
		
		# 1. Barcode search (exact match)
		barcode_item = search_by_barcode(query)
		if barcode_item:
			results.append({
				"item": barcode_item,
				"match_type": "barcode",
				"matched_field": "barcode"
			})
		
		# 2. Customer code search
		customer_items = search_by_customer_code(query)
		if customer_items:
			for item in customer_items:
				results.append({
					"item": item,
					"match_type": "customer_code",
					"matched_field": "customer_code"
				})
		
		# 3. Text search (name, code, description)
		text_items = search_by_text(query, limit)
		for item in text_items:
			results.append({
				"item": item,
				"match_type": "text",
				"matched_field": "name"
			})
		
		# Remove duplicates based on item_code
		seen_codes = set()
		unique_results = []
		for result in results:
			if result["item"]["item_code"] not in seen_codes:
				seen_codes.add(result["item"]["item_code"])
				unique_results.append(result)
		
		return {
			"success": True,
			"results": unique_results[:limit],
			"total": len(unique_results)
		}
		
	except Exception as e:
		return {
			"success": False,
			"error": str(e),
			"results": []
		}


@frappe.whitelist(allow_guest=True)
def get_pos_item_stock(item_code, warehouse=None):
	"""Get stock information for POS item."""
	try:
		# Get default warehouse if not provided
		if not warehouse:
			warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
		
		# Get stock from Bin
		bin_data = frappe.db.get_value(
			"Bin",
			{"item_code": item_code, "warehouse": warehouse},
			["actual_qty", "reserved_qty", "ordered_qty", "projected_qty"],
			as_dict=True
		)
		
		if bin_data:
			return {
				"success": True,
				"item_code": item_code,
				"warehouse": warehouse,
				"actual_qty": flt(bin_data.actual_qty),
				"reserved_qty": flt(bin_data.reserved_qty),
				"ordered_qty": flt(bin_data.ordered_qty),
				"projected_qty": flt(bin_data.projected_qty),
				"available_qty": flt(bin_data.actual_qty) - flt(bin_data.reserved_qty)
			}
		else:
			return {
				"success": True,
				"item_code": item_code,
				"warehouse": warehouse,
				"actual_qty": 0,
				"reserved_qty": 0,
				"ordered_qty": 0,
				"projected_qty": 0,
				"available_qty": 0
			}
			
	except Exception as e:
		return {
			"success": False,
			"error": str(e)
		}


@frappe.whitelist(allow_guest=True)
def get_pos_item_price(item_code, price_list=None):
	"""Get pricing information for POS item."""
	try:
		# Get default price list if not provided
		if not price_list:
			price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
		
		# Get item price
		price_data = frappe.db.get_value(
			"Item Price",
			{"item_code": item_code, "price_list": price_list},
			["price_list_rate", "currency", "valid_from", "valid_upto"],
			as_dict=True
		)
		
		# Get item's standard rate as fallback
		item = frappe.get_doc("Item", item_code)
		
		return {
			"success": True,
			"item_code": item_code,
			"price_list": price_list,
			"base_price": flt(item.standard_rate),
			"price_list_rate": flt(price_data.price_list_rate) if price_data else flt(item.standard_rate),
			"currency": price_data.currency if price_data else "INR",
			"valid_from": price_data.valid_from if price_data else None,
			"valid_upto": price_data.valid_upto if price_data else None
		}
		
	except Exception as e:
		return {
			"success": False,
			"error": str(e)
		}


@frappe.whitelist(allow_guest=True)
def get_pos_item_barcodes(item_code):
	"""Get all barcodes for an item."""
	try:
		barcodes = frappe.get_all(
			"Item Barcode",
			fields=["barcode", "barcode_type"],
			filters={"parent": item_code}
		)
		
		return {
			"success": True,
			"item_code": item_code,
			"barcodes": [b["barcode"] for b in barcodes],
			"barcode_details": barcodes
		}
		
	except Exception as e:
		return {
			"success": False,
			"error": str(e)
		}


@frappe.whitelist(allow_guest=True)
def get_pos_item_customer_codes(item_code):
	"""Get all customer codes for an item."""
	try:
		customer_items = frappe.get_all(
			"Item Customer Detail",
			fields=["customer", "ref_code", "ref_name"],
			filters={"parent": item_code}
		)
		
		return {
			"success": True,
			"item_code": item_code,
			"customer_codes": [c["ref_code"] for c in customer_items if c["ref_code"]],
			"customer_details": customer_items
		}
		
	except Exception as e:
		return {
			"success": False,
			"error": str(e)
		}


@frappe.whitelist(allow_guest=True)
def get_pos_item_variants(item_code):
	"""Get variants for a template item."""
	try:
		item = frappe.get_doc("Item", item_code)
		
		if not item.has_variants:
			return {
				"success": True,
				"item_code": item_code,
				"has_variants": False,
				"variants": []
			}
		
		# Get variants
		variants = frappe.get_all(
			"Item",
			fields=["item_code", "item_name", "standard_rate", "image", "brand", "disabled"],
			filters={"variant_of": item_code, "disabled": 0}
		)
		
		# Get variant attributes
		variant_attributes = frappe.get_all(
			"Item Variant Attribute",
			fields=["parent", "attribute", "attribute_value"],
			filters={"parent": ["in", [v["item_code"] for v in variants]]}
		)
		
		# Group attributes by variant
		attributes_by_variant = {}
		for attr in variant_attributes:
			if attr["parent"] not in attributes_by_variant:
				attributes_by_variant[attr["parent"]] = {}
			attributes_by_variant[attr["parent"]][attr["attribute"]] = attr["attribute_value"]
		
		# Enhance variants with attributes
		enhanced_variants = []
		for variant in variants:
			variant["attributes"] = attributes_by_variant.get(variant["item_code"], {})
			enhanced_variants.append(variant)
		
		return {
			"success": True,
			"item_code": item_code,
			"has_variants": True,
			"variant_based_on": item.variant_based_on,
			"variants": enhanced_variants
		}
		
	except Exception as e:
		return {
			"success": False,
			"error": str(e)
		}


@frappe.whitelist(allow_guest=True)
def get_pos_items_by_company_warehouse(company=None, warehouse=None, filters=None, fields=None, limit=50, offset=0, search_term=None):
	"""
	Get items for POS filtered by company and warehouse.
	Returns items with stock information for the specific warehouse.
	"""
	try:
		# Parse filters if provided as JSON string
		if isinstance(filters, str):
			filters = json.loads(filters)
		if isinstance(fields, str):
			fields = json.loads(fields)
		
		# Get default company if not provided
		if not company:
			company = frappe.db.get_single_value("Global Defaults", "default_company")
		
		# Get default warehouse if not provided
		if not warehouse:
			warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
		
		# Validate company and warehouse exist
		if not frappe.db.exists("Company", company):
			return {
				"success": False,
				"error": f"Company '{company}' not found"
			}
		
		if not frappe.db.exists("Warehouse", warehouse):
			return {
				"success": False,
				"error": f"Warehouse '{warehouse}' not found"
			}
		
		# Default filters for POS
		default_filters = {
			"is_sales_item": 1,
			"disabled": 0
		}
		
		# Merge with provided filters
		if filters:
			default_filters.update(filters)
		
		# Default fields for POS (minimal payload)
		default_fields = [
			"item_code", "item_name", "item_group", "stock_uom", "standard_rate",
			"is_sales_item", "disabled", "image", "brand", "description",
			"has_variants", "variant_of", "is_stock_item", "grant_commission",
			"max_discount", "valuation_rate", "weight_per_unit", "weight_uom"
		]
		
		# Use provided fields or defaults
		fields_to_fetch = fields if fields else default_fields
		
		# Add search functionality
		or_filters = []
		if search_term:
			search_term = cstr(search_term).strip()
			or_filters = [
				["item_name", "like", f"%{search_term}%"],
				["item_code", "like", f"%{search_term}%"],
				["description", "like", f"%{search_term}%"]
			]
		
		# Get items
		items = frappe.get_list(
			"Item",
			fields=fields_to_fetch,
			filters=default_filters,
			or_filters=or_filters,
			limit_page_length=cint(limit),
			limit_start=cint(offset),
			order_by="item_name asc",
			ignore_permissions=True
		)
		
		# Get total count for pagination
		total_count = frappe.db.count("Item", default_filters)
		
		# Enhance items with company/warehouse specific data
		enhanced_items = []
		for item in items:
			enhanced_item = enhance_pos_item_with_warehouse(item, company, warehouse)
			enhanced_items.append(enhanced_item)
		
		return {
			"success": True,
			"items": enhanced_items,
			"total_count": total_count,
			"has_more": (cint(offset) + len(items)) < total_count,
			"limit": cint(limit),
			"offset": cint(offset),
			"company": company,
			"warehouse": warehouse,
			"filters_applied": default_filters
		}
		
	except Exception as e:
		frappe.log_error(f"Error in get_pos_items_by_company_warehouse: {str(e)}")
		return {
			"success": False,
			"error": str(e),
			"items": [],
			"total_count": 0
		}


@frappe.whitelist(allow_guest=True)
def get_pos_item_statistics():
	"""Get POS item statistics."""
	try:
		# Get basic counts
		total_items = frappe.db.count("Item", {"is_sales_item": 1})
		active_items = frappe.db.count("Item", {"is_sales_item": 1, "disabled": 0})
		disabled_items = frappe.db.count("Item", {"is_sales_item": 1, "disabled": 1})
		items_with_variants = frappe.db.count("Item", {"is_sales_item": 1, "has_variants": 1})
		
		# Get average price
		avg_price = frappe.db.sql("""
			SELECT AVG(standard_rate) as avg_price
			FROM `tabItem`
			WHERE is_sales_item = 1 AND disabled = 0 AND standard_rate > 0
		""", as_dict=True)
		
		# Get price range
		price_range = frappe.db.sql("""
			SELECT MIN(standard_rate) as min_price, MAX(standard_rate) as max_price
			FROM `tabItem`
			WHERE is_sales_item = 1 AND disabled = 0 AND standard_rate > 0
		""", as_dict=True)
		
		# Get top brands
		top_brands = frappe.db.sql("""
			SELECT brand, COUNT(*) as count
			FROM `tabItem`
			WHERE is_sales_item = 1 AND disabled = 0 AND brand IS NOT NULL
			GROUP BY brand
			ORDER BY count DESC
			LIMIT 10
		""", as_dict=True)
		
		# Get top categories
		top_categories = frappe.db.sql("""
			SELECT item_group, COUNT(*) as count
			FROM `tabItem`
			WHERE is_sales_item = 1 AND disabled = 0
			GROUP BY item_group
			ORDER BY count DESC
			LIMIT 10
		""", as_dict=True)
		
		return {
			"success": True,
			"total_items": total_items,
			"active_items": active_items,
			"disabled_items": disabled_items,
			"items_with_variants": items_with_variants,
			"average_price": flt(avg_price[0].avg_price) if avg_price else 0,
			"price_range": {
				"min": flt(price_range[0].min_price) if price_range else 0,
				"max": flt(price_range[0].max_price) if price_range else 0
			},
			"top_brands": top_brands,
			"top_categories": top_categories
		}
		
	except Exception as e:
		return {
			"success": False,
			"error": str(e)
		}


# Helper functions
def enhance_pos_item(item):
	"""Enhance item with related data for POS."""
	try:
		# Get barcodes
		barcodes = frappe.get_all(
			"Item Barcode",
			fields=["barcode", "barcode_type"],
			filters={"parent": item["item_code"]}
		)
		
		# Get customer codes
		customer_items = frappe.get_all(
			"Item Customer Detail",
			fields=["customer", "ref_code", "ref_name"],
			filters={"parent": item["item_code"]}
		)
		
		# Get stock info (if available)
		stock_qty = None
		try:
			bin_data = frappe.db.get_value(
				"Bin",
				{"item_code": item["item_code"]},
				"actual_qty"
			)
			stock_qty = flt(bin_data) if bin_data else 0
		except:
			pass
		
		# Enhance item
		enhanced_item = {
			**item,
			"barcodes": [b["barcode"] for b in barcodes],
			"customer_codes": [c["ref_code"] for c in customer_items if c["ref_code"]],
			"stock_qty": stock_qty,
			"display_name": item.get("item_name", item.get("item_code")),
			"short_name": item.get("item_name", "")[:20] + "..." if len(item.get("item_name", "")) > 20 else item.get("item_name", ""),
			"category_display": item.get("item_group", "")
		}
		
		return enhanced_item
		
	except Exception as e:
		frappe.log_error(f"Error enhancing POS item {item.get('item_code', 'unknown')}: {str(e)}")
		return item


def enhance_pos_item_with_warehouse(item, company, warehouse):
	"""Enhance item with company and warehouse specific data for POS."""
	try:
		# Get barcodes
		barcodes = frappe.get_all(
			"Item Barcode",
			fields=["barcode", "barcode_type"],
			filters={"parent": item["item_code"]}
		)
		
		# Get customer codes
		customer_items = frappe.get_all(
			"Item Customer Detail",
			fields=["customer", "ref_code", "ref_name"],
			filters={"parent": item["item_code"]}
		)
		
		# Get stock info for specific warehouse
		stock_info = get_item_stock_info(item["item_code"], warehouse)
		
		# Get company-specific item defaults
		item_defaults = get_item_defaults(item["item_code"], company)
		
		# Get price list rate for company
		price_info = get_item_price_info(item["item_code"], company)
		
		# Enhance item
		enhanced_item = dict(item)  # Create a copy of the original item
		enhanced_item.update({
			"barcodes": [b["barcode"] for b in barcodes],
			"customer_codes": [c["ref_code"] for c in customer_items if c["ref_code"]],
			"stock_info": stock_info,
			"item_defaults": item_defaults,
			"price_info": price_info,
			"company": company,
			"warehouse": warehouse,
			"display_name": item.get("item_name", item.get("item_code")),
			"short_name": item.get("item_name", "")[:20] + "..." if len(item.get("item_name", "")) > 20 else item.get("item_name", ""),
			"category_display": item.get("item_group", ""),
			"is_available": stock_info.get("available_qty", 0) > 0,
			"stock_status": get_stock_status(stock_info.get("available_qty", 0))
		})
		
		return enhanced_item
		
	except Exception as e:
		frappe.log_error(f"Error enhancing POS item with warehouse {item.get('item_code', 'unknown')}: {str(e)}")
		# Return original item with basic enhancement
		return {
			**item,
			"company": company,
			"warehouse": warehouse,
			"barcodes": [],
			"customer_codes": [],
			"stock_info": {"available_qty": 0, "warehouse": warehouse},
			"item_defaults": {},
			"price_info": {"base_price": item.get("standard_rate", 0)},
			"is_available": False,
			"stock_status": "out_of_stock"
		}


def get_item_stock_info(item_code, warehouse):
	"""Get comprehensive stock information for an item in a specific warehouse."""
	try:
		# Get stock from Bin
		bin_data = frappe.db.get_value(
			"Bin",
			{"item_code": item_code, "warehouse": warehouse},
			["actual_qty", "reserved_qty", "ordered_qty", "projected_qty", "valuation_rate"],
			as_dict=True
		)
		
		if bin_data:
			return {
				"warehouse": warehouse,
				"actual_qty": flt(bin_data.actual_qty),
				"reserved_qty": flt(bin_data.reserved_qty),
				"ordered_qty": flt(bin_data.ordered_qty),
				"projected_qty": flt(bin_data.projected_qty),
				"available_qty": flt(bin_data.actual_qty) - flt(bin_data.reserved_qty),
				"valuation_rate": flt(bin_data.valuation_rate),
				"stock_value": flt(bin_data.actual_qty) * flt(bin_data.valuation_rate)
			}
		else:
			return {
				"warehouse": warehouse,
				"actual_qty": 0,
				"reserved_qty": 0,
				"ordered_qty": 0,
				"projected_qty": 0,
				"available_qty": 0,
				"valuation_rate": 0,
				"stock_value": 0
			}
			
	except Exception as e:
		frappe.log_error(f"Error getting stock info for {item_code} in {warehouse}: {str(e)}")
		return {
			"warehouse": warehouse,
			"actual_qty": 0,
			"reserved_qty": 0,
			"ordered_qty": 0,
			"projected_qty": 0,
			"available_qty": 0,
			"valuation_rate": 0,
			"stock_value": 0
		}


def get_item_defaults(item_code, company):
	"""Get item defaults for a specific company."""
	try:
		defaults = frappe.db.get_value(
			"Item Default",
			{"parent": item_code, "company": company},
			["default_warehouse", "default_price_list", "buying_cost_center", 
			 "default_supplier", "expense_account", "selling_cost_center", "income_account"],
			as_dict=True
		)
		
		return defaults if defaults else {}
		
	except Exception as e:
		frappe.log_error(f"Error getting item defaults for {item_code} in {company}: {str(e)}")
		return {}


def get_item_price_info(item_code, company):
	"""Get price information for an item in a specific company context."""
	try:
		# Get company's default price list
		price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
		
		# Get item price
		price_data = frappe.db.get_value(
			"Item Price",
			{"item_code": item_code, "price_list": price_list},
			["price_list_rate", "currency", "valid_from", "valid_upto"],
			as_dict=True
		)
		
		# Get item's standard rate as fallback
		item = frappe.get_doc("Item", item_code)
		
		return {
			"price_list": price_list,
			"base_price": flt(item.standard_rate),
			"price_list_rate": flt(price_data.price_list_rate) if price_data else flt(item.standard_rate),
			"currency": price_data.currency if price_data else "INR",
			"valid_from": price_data.valid_from if price_data else None,
			"valid_upto": price_data.valid_upto if price_data else None
		}
		
	except Exception as e:
		frappe.log_error(f"Error getting price info for {item_code} in {company}: {str(e)}")
		return {
			"price_list": None,
			"base_price": 0,
			"price_list_rate": 0,
			"currency": "INR",
			"valid_from": None,
			"valid_upto": None
		}


def get_stock_status(available_qty):
	"""Determine stock status based on available quantity."""
	if available_qty <= 0:
		return "out_of_stock"
	elif available_qty <= 10:  # Assuming 10 is low stock threshold
		return "low_stock"
	else:
		return "in_stock"


def search_by_barcode(barcode):
	"""Search item by barcode."""
	try:
		item_barcode = frappe.db.get_value(
			"Item Barcode",
			{"barcode": barcode},
			"parent"
		)
		
		if item_barcode:
			item = frappe.get_doc("Item", item_barcode)
			if item.is_sales_item and not item.disabled:
				return enhance_pos_item(item.as_dict())
		return None
		
	except Exception:
		return None


def search_by_customer_code(customer_code):
	"""Search items by customer code."""
	try:
		customer_items = frappe.get_all(
			"Item Customer Detail",
			fields=["parent"],
			filters={"ref_code": customer_code}
		)
		
		items = []
		for ci in customer_items:
			item = frappe.get_doc("Item", ci.parent)
			if item.is_sales_item and not item.disabled:
				items.append(enhance_pos_item(item.as_dict()))
		
		return items
		
	except Exception:
		return []


def search_by_text(query, limit=20):
	"""Search items by text (name, code, description)."""
	try:
		items = frappe.get_all(
			"Item",
			fields=["item_code", "item_name", "item_group", "stock_uom", "standard_rate",
					"is_sales_item", "disabled", "image", "brand", "description"],
			filters={
				"is_sales_item": 1,
				"disabled": 0
			},
			or_filters=[
				["item_name", "like", f"%{query}%"],
				["item_code", "like", f"%{query}%"],
				["description", "like", f"%{query}%"]
			],
			limit_page_length=limit
		)
		
		return [enhance_pos_item(item) for item in items]
		
	except Exception:
		return []

