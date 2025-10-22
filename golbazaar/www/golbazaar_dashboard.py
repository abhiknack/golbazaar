# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe

def get_context(context):
    context.title = "Golbazaar Dashboard"
    context.app_name = "golbazaar"

    # Basic stats
    context.total_users = frappe.db.count("User")
    context.total_doctypes = frappe.db.count("DocType")

    # Recent Items (fetch latest 10 Items)
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

    # Recent activities (sample)
    context.recent_activities = [
        {"title": "Golbazaar App Installed", "time": "Just now", "type": "success"},
        {"title": "Fetched recent Items", "time": "moments ago", "type": "info"},
    ]

    return context

