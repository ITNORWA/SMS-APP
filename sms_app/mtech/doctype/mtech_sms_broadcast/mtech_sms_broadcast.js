frappe.ui.form.on("Mtech SMS Broadcast", {
  refresh(frm) {
    const label = frm.doc.status === "Sent" ? "Resend SMS" : "Send SMS";
    frm.add_custom_button(label, () => {
      if (!frm.doc.message) {
        frappe.msgprint("Message is required.");
        return;
      }
      if (!frm.doc.mobile_numbers) {
        frappe.msgprint("Mobile numbers are required.");
        return;
      }

      const run = () => {
        frm.call({
          method: "send_sms",
          freeze: true,
          freeze_message: "Sending SMS...",
          callback: (r) => {
            if (r.message && r.message.success) {
              frappe.msgprint("SMS sent successfully.");
            } else {
              frappe.msgprint("Failed to send SMS. Check logs for details.");
            }
            frm.reload_doc();
          },
        });
      };

      if (frm.is_dirty() || frm.is_new()) {
        frm.save().then(run);
      } else {
        run();
      }
    });
  },
});
