# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe

def get_context(context):
	context.title = "Golbazaar"
	context.app_name = "golbazaar"
	context.app_title = "Golbazaar"
	context.app_description = "Custom Golbazaar Business Application"
	
	# Add any data you want to pass to the template
	context.features = [
		{
			"title": "Dashboard",
			"description": "Monitor your business metrics and performance",
			"icon": "📊"
		},
		{
			"title": "Settings", 
			"description": "Configure your Golbazaar application",
			"icon": "📋"
		},
		{
			"title": "Customization",
			"description": "Customize the app according to your needs", 
			"icon": "🔧"
		}
	]
	
	return context






