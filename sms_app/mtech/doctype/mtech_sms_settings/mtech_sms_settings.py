import json

import frappe
import requests
from frappe.model.document import Document

from sms_app.mtech.token_manager import _build_url

LOGIN_ENDPOINT = "/auth/token"
_SENSITIVE_KEYS = {"token", "access_token", "password", "api_key", "api_secret"}


class MtechSMSSettings(Document):
    pass


def _mask_sensitive(value):
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if key.lower() in _SENSITIVE_KEYS:
                masked[key] = "***"
            else:
                masked[key] = _mask_sensitive(item)
        return masked

    if isinstance(value, list):
        return [_mask_sensitive(item) for item in value]

    return value


def _extract_token(data):
    if not isinstance(data, dict):
        return None

    data_block = data.get("data")
    if isinstance(data_block, dict):
        return data_block.get("token") or data_block.get("access_token")

    return data.get("token") or data.get("access_token")


def _build_failure_message(status_code):
    if status_code == 405:
        return "Method Not Allowed. Check API Base URL. It should be API root only, without /auth/token."
    if status_code == 404:
        return "Auth endpoint not found. Verify API Base URL and API version path."
    if status_code in (401, 403):
        return "Authentication failed. Verify API Username and API key."
    return f"Mtech auth failed with HTTP {status_code}."


@frappe.whitelist()
def test_mtech_credentials(api_base_url=None, api_username=None, api_password=None):
    """Validate current Mtech auth settings without sending an SMS."""
    frappe.only_for("System Manager")

    settings = frappe.get_single("Mtech SMS Settings")

    base_url = (api_base_url or settings.api_base_url or "").strip()
    username = (api_username or settings.api_username or "").strip()

    password = (api_password or "").strip()
    if not password:
        try:
            password = settings.get_password("api_password")
        except Exception:
            password = ""

    missing = []
    if not base_url:
        missing.append("API Base URL")
    if not username:
        missing.append("API Username")
    if not password:
        missing.append("API Password")

    url = _build_url(base_url, LOGIN_ENDPOINT) if base_url else ""

    if missing:
        return {
            "ok": False,
            "status_code": None,
            "url": url,
            "message": "Missing required fields: " + ", ".join(missing),
            "response_excerpt": "",
        }

    payload = {"username": username, "password": password}

    try:
        response = requests.post(url, json=payload, timeout=10)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "url": url,
            "message": f"Could not reach Mtech auth endpoint: {exc}",
            "response_excerpt": "",
        }

    response_excerpt = response.text[:800]
    response_json = None
    try:
        response_json = response.json()
        response_excerpt = json.dumps(_mask_sensitive(response_json), indent=2)[:1200]
    except ValueError:
        pass

    token = _extract_token(response_json)
    success = response.status_code in (200, 201) and bool(token)

    if success:
        return {
            "ok": True,
            "status_code": response.status_code,
            "url": url,
            "message": "Credentials are valid. Token received from Mtech.",
            "response_excerpt": response_excerpt,
        }

    message = _build_failure_message(response.status_code)
    if response.status_code in (200, 201) and not token:
        message = "Auth endpoint responded but no token was returned. Check credentials and response format."

    return {
        "ok": False,
        "status_code": response.status_code,
        "url": url,
        "message": message,
        "response_excerpt": response_excerpt,
    }
