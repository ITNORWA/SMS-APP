import frappe
from sms_app.mtech.sms_client import send_sms as _send


@frappe.whitelist()
def send_sms_via_server_script(mobile, message, message_type=None, dlr_url=None, message_id=None):
    """
    Call this from ERPNext Server Scripts using:
    frappe.call(
        "sms_app.mtech.utils.send_sms_via_server_script",
        mobile=...,
        message=...,
        message_type="Transactional",
        dlr_url="https://example.com/callback",
        message_id="your-id",
    )

    The `mobile` argument can be:
    - A single number string
    - A list/tuple of numbers
    - A comma/semicolon/newline-separated string of numbers
    """
    return _send(
        mobile,
        message,
        message_type=message_type,
        dlr_url=dlr_url,
        message_id=message_id,
    )


def ensure_mtech_modules():
    """Ensure Mtech DocTypes are mapped to the Mtech module."""
    doctypes = ["Mtech SMS Settings", "Mtech SMS Log"]
    updated = []
    for dt in doctypes:
        if frappe.db.exists("DocType", dt):
            current = frappe.db.get_value("DocType", dt, "module")
            if current != "Mtech":
                frappe.db.set_value("DocType", dt, "module", "Mtech")
                updated.append((dt, current))
    frappe.db.commit()
    return {"updated": updated}


def debug_mtech_doctypes():
    """Return existence + module info for Mtech DocTypes."""
    info = {}
    for dt in ["Mtech SMS Settings", "Mtech SMS Log"]:
        exists = frappe.db.exists("DocType", dt)
        module = frappe.db.get_value("DocType", dt, "module") if exists else None
        info[dt] = {"exists": bool(exists), "module": module}
    return info


def debug_module_app():
    """Inspect module_app mapping for Mtech."""
    module_app = getattr(frappe.local, "module_app", {}) or {}
    return {
        "has_mtech": "mtech" in module_app,
        "module_app_value": module_app.get("mtech"),
        "module_app_keys_sample": [k for k in module_app.keys() if "mtech" in k],
    }


def debug_app_modules():
    """List modules per installed app (for troubleshooting)."""
    apps = frappe.get_installed_apps()
    modules = {}
    for app in apps:
        try:
            modules[app] = frappe.get_module_list(app)
        except Exception as exc:
            modules[app] = f"ERROR: {exc}"
    return modules


def rebuild_module_map():
    """Force rebuild of module map and return mapping info."""
    frappe.setup_module_map()
    return debug_module_app()
