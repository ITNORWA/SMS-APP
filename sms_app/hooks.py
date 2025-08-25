app_name = "sms_app"
app_title = "SMS App"
app_publisher = "Norwa Africa"
app_email = "it-department@norwaafrica.com"
app_license = "MIT"

# Fire a universal handler and filter internally by templates
doc_events = {
    "*": {
        "on_submit": "sms_app.api.handle_doc_event",
        "on_update_after_submit": "sms_app.api.handle_doc_event",
        "on_cancel": "sms_app.api.handle_doc_event",
        # value_change/days_* can be handled via scheduler if you need later
    }
}

scheduler_events = {
    # Optional: daily token refresh, retry failed, days_before/after
    # "cron": {
    #   "*/10 * * * *": ["sms_app.api.retry_queued"]
    # 
    }