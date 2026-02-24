import json
import re
import requests
import frappe
from uuid import uuid4
from sms_app.mtech.token_manager import get_valid_token, _build_url

# Constants
SEND_ENDPOINT = "/messaging/send"
MSISDN_PATTERN = re.compile(r"^\d{8,15}$")


def _build_message_id():
    return uuid4().hex


def _extract_raw_mobile_entries(mobile_numbers):
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

    entries = []
    for item in raw:
        if item is None:
            continue
        value = str(item).strip()
        if not value:
            continue
        entries.append(value)
    return entries


def _normalize_single_msisdn(msisdn):
    normalized = re.sub(r"[^\d+]", "", str(msisdn or "").strip())
    if normalized.startswith("+"):
        normalized = normalized[1:]
    if not MSISDN_PATTERN.fullmatch(normalized):
        return None
    return normalized


def _dedupe(items):
    seen = set()
    deduped = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def prepare_msisdns(mobile_numbers):
    raw_entries = _extract_raw_mobile_entries(mobile_numbers)
    valid = []
    invalid = []
    duplicates = []
    seen = set()

    for entry in raw_entries:
        normalized = _normalize_single_msisdn(entry)
        if not normalized:
            invalid.append(entry)
            continue

        if normalized in seen:
            duplicates.append(normalized)
            continue

        seen.add(normalized)
        valid.append(normalized)

    return {
        "valid": valid,
        "invalid": _dedupe(invalid),
        "duplicates": _dedupe(duplicates),
        "entered_count": len(raw_entries),
    }


def _normalize_msisdns(mobile_numbers):
    return prepare_msisdns(mobile_numbers).get("valid", [])


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

    recipient_info = prepare_msisdns(mobile_number)
    msisdns = recipient_info.get("valid", [])
    invalid_entries = recipient_info.get("invalid", [])
    duplicate_entries = recipient_info.get("duplicates", [])
    if not msisdns:
        error_bits = ["No valid mobile numbers provided"]
        if invalid_entries:
            error_bits.append(f"Invalid entries: {', '.join(invalid_entries[:10])}")
        if duplicate_entries:
            error_bits.append(f"Duplicate entries: {', '.join(duplicate_entries[:10])}")
        error_message = " | ".join(error_bits)
        create_sms_log(
            mobile_number,
            message,
            "Failed",
            error_message,
            reference_doctype,
            reference_doc,
        )
        if return_response:
            return {
                "success": False,
                "status": "Failed",
                "response": error_message,
                "message_id": message_id or "",
                "recipient_count": 0,
                "sent_count": 0,
                "failed_count": 0,
                "invalid_entries": invalid_entries,
                "duplicate_entries": duplicate_entries,
            }
        return False

    recipient_count = len(msisdns)

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

    sent_count = recipient_count if status == "Sent" else 0
    failed_count = recipient_count - sent_count

    if return_response:
        return {
            "success": status == "Sent",
            "status": status,
            "response": api_response,
            "message_id": payload.get("message_id"),
            "recipient_count": recipient_count,
            "sent_count": sent_count,
            "failed_count": failed_count,
            "invalid_entries": invalid_entries,
            "duplicate_entries": duplicate_entries,
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
