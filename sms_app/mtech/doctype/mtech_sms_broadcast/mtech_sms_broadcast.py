import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from sms_app.mtech.doctype.mtech_sms_template.mtech_sms_template import (
    render_template_content,
)
from sms_app.mtech.sms_client import send_sms as send_sms_via_gateway


class MtechSMSBroadcast(Document):
    @staticmethod
    def _resolve_broadcast_status(sent_count, total_count):
        if total_count <= 0:
            return "Draft"
        if sent_count <= 0:
            return "Failed"
        if sent_count < total_count:
            return "Partially Sent"
        return "Sent"

    def _get_template_values(self):
        raw_values = (self.template_values or "").strip()
        if not raw_values:
            return {}

        try:
            parsed = frappe.parse_json(raw_values)
        except Exception as exc:
            frappe.throw(_("Template Values must be valid JSON. Error: {0}").format(exc))

        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            frappe.throw(_("Template Values must be a JSON object."))
        return parsed

    def _build_message(self):
        message_to_send = (self.message or "").strip()
        if self.sms_template:
            template_doc = frappe.db.get_value(
                "Mtech SMS Template",
                self.sms_template,
                ["message_template", "is_active"],
                as_dict=True,
            )
            if not template_doc or not template_doc.get("message_template"):
                frappe.throw(_("Selected SMS Template has no message content."))
            if not cint(template_doc.get("is_active")):
                frappe.throw(_("Selected SMS Template is disabled."))

            rendered_message, missing_keys = render_template_content(
                template_doc.get("message_template"),
                self._get_template_values(),
            )
            if missing_keys:
                frappe.throw(
                    _("Missing template values for: {0}").format(", ".join(missing_keys))
                )
            message_to_send = rendered_message.strip()

        if not message_to_send:
            frappe.throw(_("Message is required. Enter a message or choose a template."))
        return message_to_send

    def _get_latest_recipient_status_map(self):
        logs = frappe.get_all(
            "Mtech SMS Log",
            filters={
                "reference_doctype": self.doctype,
                "reference_doc": self.name,
            },
            fields=["mobile_number", "status", "creation"],
            order_by="creation asc",
        )

        latest = {}
        for row in logs:
            mobile = (row.mobile_number or "").strip()
            if not mobile:
                continue
            latest[mobile] = row.status or "Failed"
        return latest

    def _update_delivery_counters_from_logs(self):
        latest = self._get_latest_recipient_status_map()
        total_recipients = len(latest)
        sent_recipients = sum(1 for current_status in latest.values() if current_status == "Sent")
        failed_recipients = max(total_recipients - sent_recipients, 0)

        self.total_recipients = total_recipients
        self.sent_recipients = sent_recipients
        self.failed_recipients = failed_recipients
        self.status = self._resolve_broadcast_status(sent_recipients, total_recipients)

    def _send_to_recipients(self, recipients):
        message_to_send = self._build_message()

        result = send_sms_via_gateway(
            recipients,
            message_to_send,
            reference_doctype=self.doctype,
            reference_doc=self.name,
            message_type=self.message_type,
            dlr_url=self.dlr_url,
            message_id=self.message_id,
            return_response=True,
        )
        attempt_sent_count = cint(result.get("sent_count") or 0)
        attempt_failed_count = cint(result.get("failed_count") or 0)

        if result.get("message_id"):
            self.message_id = result.get("message_id")
        self.rendered_message = message_to_send
        self.sent_on = frappe.utils.now()
        self.last_response = result.get("response") or ""
        self._update_delivery_counters_from_logs()
        self.save(ignore_permissions=True)
        frappe.db.commit()

        result.update(
            {
                "status": self.status,
                "recipient_count": cint(self.total_recipients),
                "sent_count": cint(self.sent_recipients),
                "failed_count": cint(self.failed_recipients),
                "attempt_sent_count": attempt_sent_count,
                "attempt_failed_count": attempt_failed_count,
                "rendered_message": self.rendered_message or "",
            }
        )
        return result

    @frappe.whitelist()
    def send_sms(self, recipient_numbers=None):
        if not self.mobile_numbers and not recipient_numbers:
            frappe.throw(_("Mobile numbers are required."))
        return self._send_to_recipients(recipient_numbers or self.mobile_numbers)

    @frappe.whitelist()
    def resend_failed_sms(self):
        latest = self._get_latest_recipient_status_map()
        failed_recipients = [
            mobile
            for mobile, current_status in latest.items()
            if current_status != "Sent"
        ]
        if not failed_recipients:
            frappe.throw(_("No failed recipients found for this broadcast."))
        return self._send_to_recipients(failed_recipients)
