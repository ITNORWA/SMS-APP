import requests
import frappe
from frappe.utils import now_datetime, get_datetime
from datetime import timedelta, datetime

# Constants based on Mtech API
LOGIN_ENDPOINT = "/auth/token"


def get_settings():
    return frappe.get_single("Mtech SMS Settings")


def _get_api_password(settings):
    try:
        password = settings.get_password("api_password")
    except Exception:
        password = None

    if password:
        return password

    # Fallback for legacy/plain values.
    return (settings.api_password or "").strip()


def _build_url(base_url: str, endpoint: str) -> str:
    return f"{(base_url or '').rstrip('/')}{endpoint}"


def _validate_settings(settings):
    missing = []
    if not settings.api_base_url:
        missing.append("API Base URL")
    if not settings.api_username:
        missing.append("API Username")
    if not _get_api_password(settings):
        missing.append("API Password")
    if missing:
        frappe.throw("Missing Mtech SMS Settings fields: " + ", ".join(missing))


def login_and_refresh_token():
    """
    Forces a login to Mtech, updates Settings with new token,
    and commits immediately.
    """
    settings = get_settings()
    _validate_settings(settings)
    api_password = _get_api_password(settings)

    # 1. Prepare Payload
    payload = {
        "username": settings.api_username,
        "password": api_password,
    }

    try:
        # 2. Call Mtech Login API
        url = _build_url(settings.api_base_url, LOGIN_ENDPOINT)
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()  # Transport-level error

        data = response.json() or {}
        data_block = data.get("data") or {}
        if isinstance(data_block, str):
            data_block = {}

        # 3. Extract Token & Expiry
        # Mtech V3 returns: {"data": {"token": "...", "expires_at": 1619503548}}
        new_token = (
            data_block.get("token")
            or data_block.get("access_token")
            or data.get("token")
            or data.get("access_token")
        )
        expires_at = (
            data_block.get("expires_at")
            or data_block.get("expires_in")
            or data.get("expires_at")
            or data.get("expires_in")
        )
        provider_status = (
            data.get("status")
            or data_block.get("status")
            or response.status_code
        )
        provider_message = data.get("message") or data_block.get("message") or ""
        status_ok = provider_status in (200, 201, "200", "201")

        if not new_token:
            detail = provider_message or response.text[:300]
            if not status_ok:
                frappe.throw(
                    f"Mtech login rejected by provider (status {provider_status}): {detail}"
                )
            frappe.throw(
                f"Mtech login response did not include a token. Provider message: {detail}"
            )

        # 4. Calculate Expiry Time
        # expires_at is a unix timestamp (seconds) or expires_in (seconds)
        if expires_at:
            try:
                expiry_time = datetime.fromtimestamp(int(expires_at))
            except Exception:
                try:
                    expiry_time = now_datetime() + timedelta(seconds=int(expires_at))
                except Exception:
                    expiry_time = now_datetime() + timedelta(seconds=3600)
        else:
            expiry_time = now_datetime() + timedelta(seconds=3600)

        # 5. Save to Settings DocType
        settings.access_token = new_token
        settings.token_expiry = expiry_time
        settings.save(ignore_permissions=True)

        # 6. Commit immediately so other processes see the new token
        frappe.db.commit()

        return new_token

    except Exception as e:
        frappe.log_error(f"Mtech Login Failed: {str(e)}", "Mtech Integration")
        raise


def debug_login_response():
    """Return raw login response for troubleshooting (do not call in production)."""
    settings = get_settings()
    _validate_settings(settings)
    url = _build_url(settings.api_base_url, LOGIN_ENDPOINT)
    payload = {
        "username": settings.api_username,
        "password": _get_api_password(settings),
    }
    response = requests.post(url, json=payload, timeout=10)
    try:
        body = response.json()
    except Exception:
        body = None
    return {
        "url": url,
        "status_code": response.status_code,
        "body": body,
        "text": response.text[:2000],
    }


def get_valid_token(force_refresh: bool = False):
    """
    Returns a valid token. Checks cache first.
    If expired or force_refresh is True, gets a new one.
    """
    if force_refresh:
        return login_and_refresh_token()

    settings = get_settings()

    # Check if token exists and if it is valid (with 60s buffer)
    if settings.access_token and settings.token_expiry:
        # Convert to datetime object just in case
        expiry = get_datetime(settings.token_expiry)

        # If we are NOT expiring in the next 60 seconds, use current token
        if expiry > (now_datetime() + timedelta(seconds=60)):
            return settings.access_token

    # If we reached here, token is missing or expired -> Refresh
    return login_and_refresh_token()


def refresh_token():
    """Scheduled job: refresh the Mtech token and log on failure."""
    try:
        return get_valid_token(force_refresh=True)
    except Exception:
        frappe.log_error("Failed to refresh Mtech SMS token", "SMS App")
        return None
