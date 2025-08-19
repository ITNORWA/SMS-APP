import requests
import uuid

# --- CONFIG ---
API_KEY = "ml34x8p5xyroy1ok35n1cs2217loz1f6nyp1ng0xzha21"   # your static API key
BASE_URL = "https://api.mtechcomm.co.ke/index.php/messaging/send"
SENDER_NAME = "NorwaAfrica"  # must be approved in Mtech portal

def send_sms(message, recipients, sender=SENDER_NAME):
    """
    Send SMS via Mtech API.
    recipients: list of phone numbers e.g. ["2547XXXXXXX"]
    """
    headers = {
        "Authorization": f"Bearer {API_KEY}"
    }

    payload = {
        "message": message,
        "sender": sender,
        "message_type": "Transactional",
        "msisdns": recipients,
        "message_id": str(uuid.uuid4()),  # unique ID per request
        "encrypted": "0"
    }

    try:
        res = requests.post(BASE_URL, json=payload, headers=headers, timeout=30)
        res.raise_for_status()
        return "Sent", payload, res.json()
    except Exception as e:
        return "Failed", payload, str(e)


if __name__ == "__main__":
    # 👇 Replace with your test phone number (must be in 2547XXXXXXX format)
    recipients = ["254710802348"]

    status, payload, response = send_sms("Hello Ronald, this is a test SMS from Norwa Africa.", recipients)

    print("STATUS:", status)
    print("PAYLOAD:", payload)
    print("RESPONSE:", response)