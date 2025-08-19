import frappe
from frappe.utils.safe_exec import safe_exec
from frappe.utils import now
from frappe import _

from .sms_client import send as send_sms

def _render_message(template_doc, doc):
    # Jinja render
    return frappe.render_template(template_doc.message or "", {"doc": doc})

def _collect_recipients(template_doc, doc):
    nums = set()

    # Single field (simple mode)
    if template_doc.receiver_phone_field:
        val = doc.get(template_doc.receiver_phone_field)
        if val:
            nums.add(str(val).strip())

    # Child rows (advanced)
    for r in getattr(template_doc, "recipients", []):
        ok = True
        if r.condition:
            # evaluate with very small context
            ctx = {"doc": doc}
            try:
                ok = bool(safe_exec(f"result = bool({r.condition})", None, ctx) or ctx.get("result"))
            except Exception:
                ok = False
        if not ok:
            continue

        if r.static_phone_number:
            nums.add(str(r.static_phone_number).strip())
        elif r.receiver_by_document_field:
            val = doc.get(r.receiver_by_document_field)
            if val:
                nums.add(str(val).strip())
    return [n for n in nums if n]

def _matches_event(template_doc, method_name:str, old_doc=None, new_doc=None):
    trig = (template_doc.trigger_event or "").strip()
    if trig == method_name:
        return True
    if trig == "value_change" and template_doc.value_change_field and old_doc:
        return (old_doc.get(template_doc.value_change_field) != new_doc.get(template_doc.value_change_field))
    return False

@frappe.whitelist()
def handle_doc_event(doc, method=None):
    """Universal hook: filters templates by doctype + event, sends SMS."""
    if isinstance(doc, str):
        doc = frappe.get_doc(frappe.form_dict.get("doctype"), doc)

    templates = frappe.get_all(
        "SMS Template",
        filters={"enabled": 1, "document_type": doc.doctype},
        fields=["name","provider","trigger_event","value_change_field","receiver_phone_field","message","dlr_url"]
    )
    if not templates:
        return

    for t in templates:
        template_doc = frappe.get_doc("SMS Template", t.name)

        if not _matches_event(template_doc, method or "", old_doc=getattr(doc, "_doc_before_save", None), new_doc=doc):
            continue

        if template_doc.condition:
            ctx = {"doc": doc}
            try:
                ok = bool(safe_exec(f"result = bool({template_doc.condition})", None, ctx) or ctx.get("result"))
                if not ok:
                    continue
            except Exception:
                continue

        recipients = _collect_recipients(template_doc, doc)
        if not recipients:
            _log("Failed", template_doc, doc, recipients, {}, {"error":"No recipients"})
            continue

        message = _render_message(template_doc, doc)
        status, payload, response = send_sms(
            provider_name = template_doc.provider,
            message       = message,
            msisdns       = recipients,
            dlr_url       = template_doc.dlr_url,
            extra         = {"message_type": getattr(template_doc, "message_type", None)}
        )
        _log(status, template_doc, doc, recipients, payload, response)

def _log(status, template_doc, doc, recipients, payload, response):
    log = frappe.new_doc("SMS Log")
    log.status = status
    log.provider = template_doc.provider
    log.template = template_doc.name
    log.document_type = doc.doctype
    log.document_name = doc.name
    log.recipients = ", ".join(recipients or [])
    log.payload = frappe.as_json(payload, indent=2)
    log.response = frappe.as_json(response, indent=2)
    if status == "Failed":
        log.error = (response if isinstance(response, str) else frappe.as_json(response))
    log.insert(ignore_permissions=True)
    frappe.db.commit()

@frappe.whitelist()
def send_test(provider:str, to:str, message:str):
    """Manual test from Desk."""
    status, payload, resp = send_sms(provider, message, [to])
    return {"status": status, "payload": payload, "response": resp}