import json
import re
import requests
import frappe
from uuid import uuid4
from sms_app.mtech.token_manager import get_valid_token, _build_url

# Constants
SEND_ENDPOINT = "/messaging/send"


def _build_message_id():
    return uuid4().hex


def _normalize_msisdns(mobile_numbers):
    if mobile_numbers is None:
        return []

    if isinstance(mobile_numbers, (list, tuple, set)):
        raw = list(mobile_numbers)
    elif isinstance(mobile_numbers, str):
        cleaned = mobile_numbers.strip()
        if not cleaned:
            raw = []
        else:
            parsed = None
            if cleaned[0] in ("[", "{"):
                try:
                    parsed = frappe.parse_json(cleaned)
                except Exception:
                    try:
                        parsed = json.loads(cleaned)
                    except Exception:
                        parsed = None
            if isinstance(parsed, (list, tuple, set)):
                raw = list(parsed)
            else:
                raw = re.split(r"[,\n;]+", cleaned)
    else:
        raw = [mobile_numbers]

    msisdns = []
    for item in raw:
        if item is None:
            continue
        value = str(item).strip()
        if not value:
            continue
        msisdns.append(value.lstrip("+"))
    return msisdns


def send_sms(
    mobile_number,
    message,
    reference_doctype=None,
    reference_doc=None,
    message_type="Transactional",
    dlr_url=None,
    message_id=None,
    encrypted=0,
    encryption_method=None,
    return_response=False,
):
    """
    Main function to send SMS.
    Handles Token logic, API calling, and Logging.
    """
    settings = frappe.get_single("Mtech SMS Settings")

    msisdns = _normalize_msisdns(mobile_number)
    if not msisdns:
        create_sms_log(
            mobile_number,
            message,
            "Failed",
            "No valid mobile numbers provided",
            reference_doctype,
            reference_doc,
        )
        return False

    # 1. Get a valid token (Gate Pass)
    token = get_valid_token()

    url = _build_url(settings.api_base_url, SEND_ENDPOINT)

    # 2. Prepare Headers & Payload
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "message_id": message_id or _build_message_id(),
        "message": message,
        "sender": settings.sender_id,
        "message_type": message_type or "Transactional",
        "msisdns": msisdns,
    }

    if dlr_url:
        payload["dlr_url"] = dlr_url
    if encrypted is not None:
        payload["encrypted"] = "1" if int(encrypted) else "0"
    if encryption_method:
        payload["encryption_method"] = encryption_method

    status = "Failed"
    api_response = ""

    try:
        # 3. Attempt to Send
        response = requests.post(url, json=payload, headers=headers, timeout=15)

        # 4. Handle "Expired Token" (401 Unauthorized) Edge Case
        if response.status_code == 401:
            # Token expired mid-process? Refresh and retry ONCE.
            new_token = get_valid_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {new_token}"
            response = requests.post(url, json=payload, headers=headers, timeout=15)

        api_response = response.text

        ok = response.status_code in (200, 201)
        if ok:
            try:
                body = response.json() or {}
                if body.get("status") not in (200, 201, "200", "201", None):
                    ok = False
            except Exception:
                pass

        status = "Sent" if ok else "Failed"

    except Exception as e:
        api_response = str(e)
        frappe.log_error(message=str(e), title="Mtech SMS Error")

    # 5. Write to Diary (Log DocType)
    create_sms_log(
        msisdns,
        message,
        status,
        api_response,
        reference_doctype,
        reference_doc,
    )

    if return_response:
        return {
            "success": status == "Sent",
            "status": status,
            "response": api_response,
        }

    return status == "Sent"


def create_sms_log(mobile, message, status, response, ref_dt, ref_dn):
    """
    Creates a record in 'Mtech SMS Log'
    """
    mobiles = mobile if isinstance(mobile, (list, tuple, set)) else [mobile]
    for item in mobiles:
        log = frappe.get_doc(
            {
                "doctype": "Mtech SMS Log",
                "mobile_number": item,
                "message_content": message,
                "status": status,
                "api_response": response,
                "sent_on": frappe.utils.now(),
                # Optional: Link to invoice/customer if provided
                "reference_doctype": ref_dt,
                "reference_doc": ref_dn,
            }
        )
        log.insert(ignore_permissions=True)
    frappe.db.commit()
