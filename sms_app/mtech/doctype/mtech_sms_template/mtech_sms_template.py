import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z_][\w]*)\s*}}")


class MtechSMSTemplate(Document):
    pass


def render_template_content(template_content, values=None):
    values = values or {}
    missing_keys = []

    def replace(match):
        key = match.group(1)
        if key in values and values[key] is not None:
            return cstr(values[key])
        missing_keys.append(key)
        return match.group(0)

    rendered_message = PLACEHOLDER_PATTERN.sub(replace, cstr(template_content or ""))
    return rendered_message, sorted(set(missing_keys))


@frappe.whitelist()
def preview_message(template_name, template_values=None):
    if not template_name:
        frappe.throw(_("Template Name is required."))

    template_content = frappe.db.get_value(
        "Mtech SMS Template",
        template_name,
        "message_template",
    )
    if not template_content:
        frappe.throw(_("Template does not exist or has no message content."))

    values = {}
    if template_values:
        parsed = frappe.parse_json(template_values)
        if parsed and not isinstance(parsed, dict):
            frappe.throw(_("Template Values must be a JSON object."))
        values = parsed or {}

    rendered_message, missing_keys = render_template_content(template_content, values)
    return {
        "rendered_message": rendered_message,
        "missing_placeholders": missing_keys,
    }
