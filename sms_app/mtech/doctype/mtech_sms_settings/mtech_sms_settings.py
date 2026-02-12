import ipaddress
import json

import frappe
import requests
from frappe.model.document import Document

from sms_app.mtech.token_manager import _build_url

LOGIN_ENDPOINT = "/auth/token"
_SENSITIVE_KEYS = {"token", "access_token", "password", "api_key", "api_secret"}
_IP_LOOKUP_URLS = [
    ("https://api.ipify.org?format=json", "json"),
    ("https://ifconfig.me/ip", "text"),
    ("https://checkip.amazonaws.com", "text"),
    ("https://ipinfo.io/ip", "text"),
]


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


def _validate_ip(value):
    candidate = (value or "").strip()
    if "\n" in candidate:
        candidate = candidate.splitlines()[0].strip()

    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None

    return candidate


@frappe.whitelist()
def get_outbound_public_ip():
    """Return the public egress IP for the current server."""
    frappe.only_for("System Manager")

    errors = []
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "User-Agent": "sms_app_ip_probe/1.0",
    }

    for url, mode in _IP_LOOKUP_URLS:
        try:
            response = requests.get(url, headers=headers, timeout=8)
        except requests.RequestException as exc:
            errors.append(f"{url}: request failed ({exc})")
            continue

        if response.status_code != 200:
            errors.append(f"{url}: HTTP {response.status_code}")
            continue

        ip_candidate = ""
        if mode == "json":
            try:
                body = response.json() or {}
            except ValueError:
                errors.append(f"{url}: invalid JSON response")
                continue

            if isinstance(body, dict):
                ip_candidate = body.get("ip") or body.get("query") or ""
        else:
            ip_candidate = response.text or ""

        ip_value = _validate_ip(ip_candidate)
        if ip_value:
            return {
                "ok": True,
                "ip": ip_value,
                "provider_url": url,
                "message": "Outbound public IP detected from this server.",
            }

        errors.append(f"{url}: no valid IP in response")

    return {
        "ok": False,
        "ip": None,
        "provider_url": None,
        "message": "Could not determine outbound public IP from this server.",
        "details": errors[:4],
    }


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
