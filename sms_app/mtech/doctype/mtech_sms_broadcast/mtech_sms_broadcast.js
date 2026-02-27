frappe.ui.form.on("Mtech SMS Broadcast", {
	refresh(frm) {
		apply_minimal_layout(frm);
		apply_recipient_mode_ui(frm);
		render_primary_banner(frm);
		add_send_button(frm);
		add_resend_failed_button(frm);
	},

	recipient_mode(frm) {
		apply_recipient_mode_ui(frm);
		render_primary_banner(frm);
	},

	message(frm) {
		render_primary_banner(frm);
	},

	contact(frm) {
		if (
			get_recipient_mode(frm) === "Single Contact" &&
			frm.doc.contact &&
			!String(frm.doc.contact_mobile_number || "").trim()
		) {
			frappe.show_alert(
				{
					message: __(
						"Selected contact has no Mobile No. Enter one manually in Mobile Numbers."
					),
					indicator: "orange",
				},
				7
			);
		}
		render_primary_banner(frm);
	},

	contacts(frm) {
		warn_missing_multiple_contact_mobiles(frm);
		render_primary_banner(frm);
	},

	contact_mobile_number(frm) {
		render_primary_banner(frm);
	},

	mobile_numbers(frm) {
		render_primary_banner(frm);
	},
});

function get_recipient_mode(frm) {
	return frm.doc.recipient_mode === "Multiple Contacts"
		? "Multiple Contacts"
		: "Single Contact";
}

function apply_minimal_layout(frm) {
	const advanced_fields = [
		"naming_series",
		"sms_template",
		"template_values",
		"rendered_message",
		"message_type",
		"dlr_url",
		"message_id",
		"status",
		"total_recipients",
		"sent_recipients",
		"failed_recipients",
		"sent_on",
		"last_response",
	];

	frm.toggle_display(advanced_fields, false);
	frm.set_df_property(
		"recipient_mode",
		"description",
		__(
			"If Single Contact is selected, use Contact Link for one recipient. If Multiple Contacts is selected, choose contacts from the list."
		)
	);
	frm.set_df_property(
		"message",
		"description",
		__("Type the exact SMS text recipients should receive.")
	);
	frm.set_df_property(
		"contact",
		"description",
		__("Use this for one recipient when Recipient Mode is Single Contact.")
	);
	frm.set_df_property(
		"contacts",
		"description",
		__("Use this when Recipient Mode is Multiple Contacts.")
	);
	frm.set_df_property(
		"contact_mobile_number",
		"description",
		__("Loaded from Contact.Mobile No.")
	);
	frm.set_df_property(
		"mobile_numbers",
		"description",
		__("Add extra numbers separated by comma, semicolon, or new line.")
	);
	frm.set_df_property(
		"message",
		"placeholder",
		__("Example: Hello, your invoice is ready for collection.")
	);
	frm.set_df_property(
		"mobile_numbers",
		"placeholder",
		__("254712345678\n254700000000")
	);
	frm.refresh_fields([
		"recipient_mode",
		"message",
		"contact",
		"contact_mobile_number",
		"contacts",
		"mobile_numbers",
	]);
}

function apply_recipient_mode_ui(frm) {
	const single_contact_mode = get_recipient_mode(frm) === "Single Contact";

	frm.toggle_display("contact", single_contact_mode);
	frm.toggle_display("contact_mobile_number", single_contact_mode);
	frm.toggle_display("contacts", !single_contact_mode);

	frm.refresh_fields(["contact", "contact_mobile_number", "contacts"]);

	if (!single_contact_mode) {
		warn_missing_multiple_contact_mobiles(frm);
	}
}

function add_send_button(frm) {
	if (frm.doc.docstatus !== 0) {
		return;
	}

	const label = frm.doc.status === "Sent" ? __("Send Again") : __("Send SMS");
	frm.add_custom_button(label, () => {
		const message = (frm.doc.message || "").trim();
		if (!message) {
			frappe.msgprint(__("Enter the message before sending."));
			return;
		}

		const recipient_validation = validate_recipients(
			collect_recipient_sources(frm)
		);
		if (!recipient_validation.entered_count) {
			frappe.msgprint(recipient_prompt_message(frm));
			return;
		}
		if (!recipient_validation.final_count) {
			frappe.msgprint(
				recipient_summary_html(recipient_validation, {
					title: __("No valid recipients found."),
					include_lists: true,
				})
			);
			return;
		}

		const confirmation = recipient_summary_html(recipient_validation, {
			title: __("Ready to send."),
			include_lists: true,
		});

		const run = () => {
			frm.call({
				doc: frm.doc,
				method: "send_sms",
				args: {
					recipient_numbers: recipient_validation.valid_numbers,
				},
				freeze: true,
				freeze_message: __("Sending SMS..."),
				callback: (r) => {
					const result = r.message || {};
					const sent_count = Number(
						result.attempt_sent_count ?? result.sent_count ?? 0
					);
					const failed_count = Number(
						result.attempt_failed_count ?? result.failed_count ?? 0
					);
					const invalid_count = Number((result.invalid_entries || []).length);
					const duplicate_count = Number((result.duplicate_entries || []).length);

					if (result.status === "Sent") {
						frappe.msgprint(
							__(
								"Message sent to {0} recipient(s). Invalid: {1}, Duplicates removed: {2}.",
								[sent_count, invalid_count, duplicate_count]
							)
						);
					} else if (result.status === "Partially Sent") {
						frappe.msgprint(
							__(
								"Sent: {0}, Failed: {1}, Invalid: {2}, Duplicates removed: {3}.",
								[sent_count, failed_count, invalid_count, duplicate_count]
							)
						);
					} else {
						frappe.msgprint(
							__("Failed to send SMS. Check delivery logs for details.")
						);
					}
					frm.reload_doc();
				},
			});
		};

		if (frm.is_dirty() || frm.is_new()) {
			frm.save().then(() => frappe.confirm(confirmation, run));
		} else {
			frappe.confirm(confirmation, run);
		}
	});
}

function add_resend_failed_button(frm) {
	if (frm.is_new()) {
		return;
	}

	const failed_count = Number(frm.doc.failed_recipients || 0);
	if (failed_count <= 0) {
		return;
	}

	frm.add_custom_button(__("Resend Failed"), () => {
		const confirmation = __(
			"Resend this message to {0} failed recipient(s)?",
			[failed_count]
		);
		frappe.confirm(confirmation, () => {
			frm.call({
				doc: frm.doc,
				method: "resend_failed_sms",
				freeze: true,
				freeze_message: __("Resending SMS..."),
				callback: (r) => {
					const result = r.message || {};
					const sent_count = Number(
						result.attempt_sent_count ?? result.sent_count ?? 0
					);
					const failed_after_retry = Number(result.failed_count || 0);
					if (result.status === "Sent" || result.status === "Partially Sent") {
						frappe.msgprint(
							__("Retry complete. Sent: {0}, Remaining failed: {1}.", [
								sent_count,
								failed_after_retry,
							])
						);
					} else {
						frappe.msgprint(
							__("Retry failed. Check delivery logs for details.")
						);
					}
					frm.reload_doc();
				},
			});
		});
	});
}

function render_primary_banner(frm) {
	frm.set_intro(null);
	frm.dashboard.clear_headline();

	const status = frm.doc.status || "Draft";
	const draft_like = frm.is_new() || status === "Draft";
	if (draft_like) {
		const recipient_validation = validate_recipients(
			collect_recipient_sources(frm)
		);
		if (!recipient_validation.entered_count) {
			frm.set_intro(recipient_intro_message(frm), "blue");
			return;
		}

		const banner = __(
			"Recipients ready: {0}/{1} | Invalid: {2} | Duplicates removed: {3}",
			[
				recipient_validation.final_count,
				recipient_validation.entered_count,
				recipient_validation.invalid_entries.length,
				recipient_validation.duplicate_entries.length,
			]
		);
		let color = "red";
		if (recipient_validation.final_count) {
			color =
				recipient_validation.invalid_entries.length ||
				recipient_validation.duplicate_entries.length
					? "orange"
					: "green";
		}
		frm.dashboard.set_headline_alert(banner, color);
		return;
	}

	render_delivery_status_banner(frm);
}

function render_delivery_status_banner(frm) {
	const total = Number(frm.doc.total_recipients || 0);
	const sent = Number(frm.doc.sent_recipients || 0);
	const failed = Number(frm.doc.failed_recipients || 0);
	const status = frm.doc.status || "Draft";

	if (!total && status === "Draft") {
		return;
	}

	const color_map = {
		Sent: "green",
		"Partially Sent": "orange",
		Failed: "red",
		Draft: "blue",
	};
	const color = color_map[status] || "blue";
	const message = __("Status: {0} | Total: {1} | Sent: {2} | Failed: {3}", [
		status,
		total,
		sent,
		failed,
	]);
	frm.dashboard.set_headline_alert(message, color);
}

function recipient_prompt_message(frm) {
	if (get_recipient_mode(frm) === "Multiple Contacts") {
		return __("Select one or more contacts or enter at least one mobile number.");
	}
	return __("Select a contact or enter at least one mobile number.");
}

function recipient_intro_message(frm) {
	if (get_recipient_mode(frm) === "Multiple Contacts") {
		return __(
			"Select one or more contacts and/or add mobile numbers, then click Send SMS."
		);
	}
	return __("Select a contact and/or add mobile numbers, then click Send SMS.");
}

function collect_recipient_sources(frm) {
	const sources = [];
	const recipient_mode = get_recipient_mode(frm);
	const extra_numbers = String(frm.doc.mobile_numbers || "").trim();

	if (recipient_mode === "Multiple Contacts") {
		const multiple_contact_entries = collect_multiple_contact_entries(frm);
		if (multiple_contact_entries.length) {
			sources.push(multiple_contact_entries);
		}
	} else {
		const contact_mobile = String(frm.doc.contact_mobile_number || "").trim();
		if (contact_mobile) {
			sources.push(contact_mobile);
		}
	}
	if (extra_numbers) {
		sources.push(extra_numbers);
	}
	return sources;
}

function collect_multiple_contact_entries(frm) {
	const rows = Array.isArray(frm.doc.contacts) ? frm.doc.contacts : [];
	return rows
		.map((row) => {
			const mobile = String(row.mobile_no || "").trim();
			if (mobile) {
				return mobile;
			}
			return String(row.contact || "").trim();
		})
		.filter((entry) => entry);
}

function warn_missing_multiple_contact_mobiles(frm) {
	if (get_recipient_mode(frm) !== "Multiple Contacts") {
		return;
	}

	const rows = Array.isArray(frm.doc.contacts) ? frm.doc.contacts : [];
	const missing_mobile_count = rows.filter(
		(row) => String(row.contact || "").trim() && !String(row.mobile_no || "").trim()
	).length;
	if (!missing_mobile_count) {
		return;
	}

	frappe.show_alert(
		{
			message: __(
				"{0} selected contact(s) have no Mobile No. Add manual numbers for them if needed.",
				[missing_mobile_count]
			),
			indicator: "orange",
		},
		7
	);
}

function validate_recipients(mobile_numbers) {
	const entries = extract_recipient_entries(mobile_numbers);
	const valid_numbers = [];
	const invalid_entries = [];
	const duplicate_entries = [];
	const seen = new Set();

	entries.forEach((entry) => {
		const normalized = normalize_msisdn(entry);
		if (!normalized) {
			if (!invalid_entries.includes(entry)) {
				invalid_entries.push(entry);
			}
			return;
		}

		if (seen.has(normalized)) {
			if (!duplicate_entries.includes(normalized)) {
				duplicate_entries.push(normalized);
			}
			return;
		}

		seen.add(normalized);
		valid_numbers.push(normalized);
	});

	return {
		entered_count: entries.length,
		final_count: valid_numbers.length,
		valid_numbers: valid_numbers,
		invalid_entries: invalid_entries,
		duplicate_entries: duplicate_entries,
	};
}

function extract_recipient_entries(mobile_numbers) {
	if (!mobile_numbers) {
		return [];
	}

	if (Array.isArray(mobile_numbers)) {
		return mobile_numbers.flatMap((value) => extract_recipient_entries(value));
	}

	const cleaned = String(mobile_numbers).trim();
	if (!cleaned) {
		return [];
	}

	try {
		const parsed = JSON.parse(cleaned);
		if (Array.isArray(parsed)) {
			return parsed
				.map((item) => String(item || "").trim())
				.filter((item) => item);
		}
	} catch (error) {
		// Fallback to delimiter split when input is not JSON.
	}

	return cleaned
		.split(/[,\n;]+/)
		.map((value) => value.trim())
		.filter((value) => value);
}

function normalize_msisdn(value) {
	let normalized = String(value || "")
		.trim()
		.replace(/[^\d+]/g, "");
	if (normalized.startsWith("+")) {
		normalized = normalized.slice(1);
	}
	if (!/^\d{8,15}$/.test(normalized)) {
		return null;
	}
	return normalized;
}

function recipient_summary_html(validation, opts = {}) {
	const title = opts.title || __("Recipient Validation");
	const lines = [
		`<b>${escape_html(title)}</b>`,
		__("Entered: {0}", [validation.entered_count]),
		__("Valid unique recipients: {0}", [validation.final_count]),
		__("Duplicates removed: {0}", [validation.duplicate_entries.length]),
		__("Invalid entries: {0}", [validation.invalid_entries.length]),
	];

	if (opts.include_lists && validation.invalid_entries.length) {
		lines.push(
			__("Invalid sample: {0}", [
				escape_html(validation.invalid_entries.slice(0, 5).join(", ")),
			])
		);
	}
	if (opts.include_lists && validation.duplicate_entries.length) {
		lines.push(
			__("Duplicate sample: {0}", [
				escape_html(validation.duplicate_entries.slice(0, 5).join(", ")),
			])
		);
	}

	return lines.join("<br>");
}

function escape_html(value) {
	const raw = String(value || "");
	if (frappe.utils && frappe.utils.escape_html) {
		return frappe.utils.escape_html(raw);
	}
	return raw
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/\"/g, "&quot;")
		.replace(/'/g, "&#039;");
}
