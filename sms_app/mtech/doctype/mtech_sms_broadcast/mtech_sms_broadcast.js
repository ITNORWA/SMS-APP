frappe.ui.form.on("Mtech SMS Broadcast", {
	refresh(frm) {
		render_status_banner(frm);
		frm.set_query("sms_template", () => ({
			filters: { is_active: 1 },
		}));
		add_send_button(frm);
		add_resend_failed_button(frm);
		add_view_logs_button(frm);
	},

	sms_template(frm) {
		apply_template_message(frm);
	},
});

function add_send_button(frm) {
	if (frm.doc.docstatus !== 0) {
		return;
	}

	const label = frm.doc.status === "Sent" ? __("Resend SMS") : __("Send SMS");
	frm.add_custom_button(label, () => {
		const recipient_validation = validate_recipients(frm.doc.mobile_numbers);
		if (!recipient_validation.entered_count) {
			frappe.msgprint(__("Enter at least one mobile number."));
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

		const template_check = validate_template_requirements(frm);
		if (template_check.error) {
			frappe.msgprint(template_check.error);
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

function add_view_logs_button(frm) {
	if (frm.is_new()) {
		return;
	}

	frm.add_custom_button(__("View Delivery Logs"), () => {
		frappe.set_route("List", "Mtech SMS Log", {
			reference_doctype: frm.doctype,
			reference_doc: frm.doc.name,
		});
	});
}

function render_status_banner(frm) {
	frm.dashboard.clear_headline();
	if (frm.is_new()) {
		return;
	}

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

function apply_template_message(frm) {
	if (!frm.doc.sms_template) {
		return;
	}

	frappe.db
		.get_value("Mtech SMS Template", frm.doc.sms_template, "message_template")
		.then((r) => {
			const template_message = (r.message && r.message.message_template) || "";
			if (!template_message) {
				return;
			}

			const current_message = (frm.doc.message || "").trim();
			if (!current_message || current_message === template_message) {
				frm.set_value("message", template_message);
				return;
			}

			frappe.confirm(
				__("Replace current message with selected template content?"),
				() => frm.set_value("message", template_message)
			);
		});
}

function validate_template_requirements(frm) {
	const raw_message = (frm.doc.message || "").trim();
	if (!raw_message) {
		return {
			error: __("Message is required. Enter a message or choose a template."),
		};
	}

	if (!frm.doc.sms_template) {
		return {};
	}

	const parse_result = parse_template_values(frm.doc.template_values);
	if (parse_result.error) {
		return {
			error: parse_result.error,
		};
	}

	const missing_keys = find_missing_placeholders(raw_message, parse_result.values);
	if (missing_keys.length) {
		return {
			error: __("Missing template values for: {0}", [missing_keys.join(", ")]),
		};
	}

	return {};
}

function parse_template_values(raw_values) {
	const trimmed = String(raw_values || "").trim();
	if (!trimmed) {
		return { values: {} };
	}

	try {
		const parsed = JSON.parse(trimmed);
		if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
			return {
				error: __("Template Values must be a JSON object."),
			};
		}
		return { values: parsed };
	} catch (error) {
		return {
			error: __("Template Values must be valid JSON."),
		};
	}
}

function find_missing_placeholders(template_message, values) {
	const found = new Set();
	const missing = [];
	const pattern = /{{\s*([a-zA-Z_][\w]*)\s*}}/g;
	let match = null;
	while ((match = pattern.exec(String(template_message || ""))) !== null) {
		const key = match[1];
		if (found.has(key)) {
			continue;
		}
		found.add(key);
		if (!Object.prototype.hasOwnProperty.call(values, key) || values[key] === null) {
			missing.push(key);
		}
	}
	return missing;
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
