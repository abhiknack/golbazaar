"""
Override POS Invoice validation to bypass permission checks when creating invoices via API
"""
import frappe
from erpnext.accounts.doctype.pos_invoice.pos_invoice import POSInvoice


class CustomPOSInvoice(POSInvoice):
    """Custom POS Invoice class that overrides validate_pos_opening_entry to bypass permissions"""
    
    def validate_pos_opening_entry(self):
        """Override to use frappe.db.get_all with ignore_permissions=True"""
        # Use db.get_all with ignore_permissions to bypass permission checks
        opening_entries = frappe.db.get_all(
            "POS Opening Entry",
            filters={"pos_profile": self.pos_profile, "status": "Open", "docstatus": 1},
            ignore_permissions=True
        )
        if len(opening_entries) == 0:
            frappe.throw(
                title=frappe._("POS Opening Entry Missing"),
                msg=frappe._("No open POS Opening Entry found for POS Profile {0}.").format(
                    frappe.bold(self.pos_profile)
                ),
            )

