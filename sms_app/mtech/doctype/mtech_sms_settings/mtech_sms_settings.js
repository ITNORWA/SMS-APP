frappe.ui.form.on("Mtech SMS Settings", {
  refresh(frm) {
    frm.add_custom_button("Test Credentials", () => {
      const api_base_url = (frm.doc.api_base_url || "").trim();
      const api_username = (frm.doc.api_username || "").trim();
      const entered_password = frm.doc.api_password || "";
      const api_password = /^\*+$/.test(entered_password) ? "" : entered_password;

      if (!api_base_url || !api_username) {
        frappe.msgprint("Fill API Base URL and API Username first.");
        return;
      }

      frappe.call({
        method: "sms_app.mtech.doctype.mtech_sms_settings.mtech_sms_settings.test_mtech_credentials",
        args: {
          api_base_url,
          api_username,
          api_password,
        },
        freeze: true,
        freeze_message: "Validating Mtech credentials...",
        callback: (r) => {
          const res = r.message || {};
          const title = res.ok ? "Credentials Valid" : "Credentials Check Failed";
          const indicator = res.ok ? "green" : "red";

          const details = [
            res.message || "No response message.",
            res.status_code ? `HTTP ${res.status_code}` : "No HTTP status",
            res.url ? `URL: ${res.url}` : "",
          ].filter(Boolean);

          let message = details.join("<br>");
          if (res.response_excerpt) {
            message += `<br><br><pre style="white-space: pre-wrap;">${frappe.utils.escape_html(res.response_excerpt)}</pre>`;
          }

          frappe.msgprint({ title, indicator, message });
        },
      });
    });
  },
});
