import uuid
import time
import requests
import frappe
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password

def _get_provider(provider_name: str):
    p = frappe.get_doc("SMS Provider", provider_name)
    if not p.enabled:
        frappe.throw(f"SMS Provider '{provider_name}' is disabled")
    return p

def _decrypt(value, doctype, name, fieldname):
    # decrypt only for password fields stored with Encryption
    try:
        return get_decrypted_password(doctype, name, fieldname, raise_exception=False) or value
    except Exception:
        return value

def _ensure_token(provider):
    if provider.auth_type != "Bearer Token":
        return

    needs_refresh = False
    if not provider.token:
        needs_refresh = True
    elif provider.token_expiry:
        # refresh 60 seconds before expiry
        needs_refresh = (provider.token_expiry - now_datetime()).total_seconds() < 60

    if not needs_refresh:
        return

    if not provider.auth_url:
        frappe.throw("Auth URL is required for Bearer Token providers")

    payload = {}
    # Common patterns (username/password or api_key)
    if provider.username:
        payload["username"] = _decrypt(provider.username, "SMS Provider", provider.name, "username")
    if provider.password:
        payload["password"] = _decrypt(provider.password, "SMS Provider", provider.name, "password")
    if provider.api_key:
        payload["api_key"] = _decrypt(provider.api_key, "SMS Provider", provider.name, "api_key")

    res = requests.post(provider.auth_url, json=payload, timeout=30)
    res.raise_for_status()
    data = res.json()

    # Try common token keys
    token = data.get("data", {}).get("token") or data.get("token")
    expiry = data.get("data", {}).get("expires_at") or data.get("expires_at")

    if not token:
        frappe.throw(f"Token not found in auth response: {data}")

    provider.db_set("token", token)
    if expiry:
        # if server returns unix timestamp
        if isinstance(expiry, (int, float)):
            provider.db_set("token_expiry", frappe.utils.add_to_date("1970-01-01", seconds=int(expiry)))
        else:
            provider.db_set("token_expiry", expiry)
    provider.reload()

def _headers(provider):
    headers = {}
    # auth
    if provider.auth_type == "Bearer Token" and provider.token:
        headers["Authorization"] = f"Bearer {provider.token}"
    elif provider.auth_type == "Basic" and provider.username:
        from base64 import b64encode
        user = _decrypt(provider.username, "SMS Provider", provider.name, "username") or ""
        pwd  = _decrypt(provider.password, "SMS Provider", provider.name, "password") or ""
        headers["Authorization"] = "Basic " + b64encode(f"{user}:{pwd}".encode()).decode()
    elif provider.auth_type == "API Key" and provider.api_key:
        headers["Authorization"] = f"ApiKey {_decrypt(provider.api_key,'SMS Provider',provider.name,'api_key')}"

    # custom headers from child table
    for h in provider.headers:
        headers[h.key] = h.value
    return headers

def _compose_payload(provider, message, msisdns:list, message_id:str, dlr_url:str=None, extra:dict=None):
    params = { (provider.message_param or "message"): message,
               (provider.recipient_param or "msisdns"): msisdns,
               (provider.message_id_param or "message_id"): message_id }
    if dlr_url and provider.dlr_url_param:
        params[provider.dlr_url_param] = dlr_url

    # static params from child table
    for p in provider.static_params:
        params[p.key] = p.value

    # user-supplied extras (e.g., message_type/sender)
    if extra:
        params.update(extra)
    # sensible defaults
    if provider.sender_name:
        params.setdefault("sender", provider.sender_name)
    return params

def send(provider_name:str, message:str, msisdns:list, dlr_url:str=None, extra:dict=None):
    """Generic send that works for Mtech and other vendors by config-only."""
    provider = _get_provider(provider_name)
    _ensure_token(provider)

    payload = _compose_payload(
        provider=provider,
        message=message,
        msisdns=msisdns,
        message_id=str(uuid.uuid4()),
        dlr_url=dlr_url,
        extra=extra or {}
    )
    headers = _headers(provider)

    # POST or GET based on provider config
    if provider.use_post:
        res = requests.post(provider.base_url, json=payload, headers=headers, timeout=45)
    else:
        res = requests.get(provider.base_url, params=payload, headers=headers, timeout=45)

    # log helpful info even on non-200
    try:
        data = res.json()
    except Exception:
        data = {"text": res.text}

    status = "Sent" if res.ok else "Failed"
    return status, payload, data