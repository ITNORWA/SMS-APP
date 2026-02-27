app_name = "sms_app"
app_title = "SMS App"
app_publisher = "Norwa Africa"
app_email = "it-department@norwaafrica.com"
app_license = "MIT"
app_description = "Mtech SMS integration app for Frappe/ERPNext"

# Mtech-only: no generic DocType triggers
doc_events = {}

override_whitelisted_methods = {
    "frappe.core.doctype.sms_settings.sms_settings.send_sms": "sms_app.mtech.utils.send_sms",
}

scheduler_events = {
    # Refresh tokens every 50 minutes (Mtech expires in 60m)
    "cron": {
        "*/50 * * * *": [
            "sms_app.mtech.token_manager.refresh_token"
        ]
    }
}
