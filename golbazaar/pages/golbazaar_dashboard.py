# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe

def get_context(context):
	context.title = "Golbazaar Dashboard"
	context.app_name = "golbazaar"
	
	# Get some basic stats for the dashboard
	context.total_users = frappe.db.count("User")
	context.total_doctypes = frappe.db.count("DocType")
	
	# Add recent activity or other dashboard data here
	context.recent_activities = [
		{"title": "Golbazaar App Installed", "time": "Just now", "type": "success"},
		{"title": "Custom DocType Created", "time": "2 minutes ago", "type": "info"},
		{"title": "Dashboard Configured", "time": "5 minutes ago", "type": "info"}
	]
	
	return context






