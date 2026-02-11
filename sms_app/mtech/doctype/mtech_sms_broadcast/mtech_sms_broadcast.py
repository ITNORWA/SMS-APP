import frappe
from frappe.model.document import Document

from sms_app.mtech.sms_client import send_sms


class MtechSMSBroadcast(Document):
    @frappe.whitelist()
    def send_sms(self):
        if not self.message:
            frappe.throw("Message is required.")
        if not self.mobile_numbers:
            frappe.throw("Mobile numbers are required.")

        result = send_sms(
            self.mobile_numbers,
            self.message,
            reference_doctype=self.doctype,
            reference_doc=self.name,
            message_type=self.message_type,
            dlr_url=self.dlr_url,
            message_id=self.message_id,
            return_response=True,
        )

        self.status = "Sent" if result.get("success") else "Failed"
        self.sent_on = frappe.utils.now()
        self.last_response = result.get("response") or ""
        self.save(ignore_permissions=True)
        frappe.db.commit()

        return result
