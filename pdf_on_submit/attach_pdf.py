# Copyright (c) 2019, Raffael Meyer and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.core.api.file import create_new_folder
from frappe.model.naming import _format_autoname
from frappe.realtime import publish_realtime
from frappe.translate import print_language
from frappe.utils.weasyprint import PrintFormatGenerator
from frappe.utils.pdf import get_pdf


def attach_pdf(doc, event=None):
	settings = frappe.get_single("PDF on Submit Settings")

	if enabled_doctypes := settings.get("enabled_for", {"document_type": doc.doctype}):
		enabled_doctype = enabled_doctypes[0]
	else:
		frappe.log_error(f"No enabled doctype found for {doc.doctype}")
		return

	auto_name = enabled_doctype.auto_name
	print_format = enabled_doctype.print_format
	letter_head = enabled_doctype.letter_head
	target_folder = getattr(enabled_doctype, 'target_folder', 'Home')  # Default to 'Home' if not set

	frappe.log(f"Generating PDF for {doc.doctype} {doc.name} with print format {print_format}")

	try:
		pdf_data = PrintFormatGenerator(print_format, doc, letter_head).render_pdf()
		if pdf_data is None:
			frappe.log_error("PDF data is None. Skipping attachment.")
			return
		else:
			frappe.log(f"PDF data generated successfully for {doc.name}")
	except TypeError as e:
		frappe.log_error(f"Error generating PDF: {e}")
		return
	except Exception as e:
		frappe.log_error(f"Unexpected error generating PDF: {e}")
		return

	save_and_attach(pdf_data, doc.doctype, doc.name, target_folder, auto_name)
	frappe.log(f"PDF saved and attached successfully for {doc.name}")


def execute(
	doctype,
	name,
	title=None,
	lang=None,
	show_progress=True,
	auto_name=None,
	print_format=None,
	letter_head=None,
):
	"""
	Queue calls this method, when it's ready.

	1. Create necessary folders
	2. Get raw PDF data
	3. Save PDF file and attach it to the document
	"""

	def publish_progress(percent):
		publish_realtime(
			"progress",
			{"percent": percent, "title": _("Creating PDF ..."), "description": None},
			doctype=doctype,
			docname=name,
		)

	if show_progress:
		publish_progress(0)

	doctype_folder = create_folder(doctype, "Home")
	title_folder = create_folder(title, doctype_folder) if title else None
	target_folder = title_folder or doctype_folder

	if show_progress:
		publish_progress(33)

	with print_language(lang):
		if frappe.db.get_value("Print Format", print_format, "print_format_builder_beta"):
			doc = frappe.get_doc(doctype, name)
			try:
				pdf_data = PrintFormatGenerator(print_format, doc, letter_head).render_pdf()
				if pdf_data is None:
					frappe.log_error("PDF data is None. Skipping attachment.")
					return
				else:
					frappe.log(f"PDF data generated successfully for {name}")
			except TypeError as e:
				frappe.log_error(f"Error generating PDF: {e}")
				return
		else:
			pdf_data = get_pdf_data(doctype, name, print_format, letter_head)

	if doctype == "Sales Invoice" and "eu_einvoice" in frappe.get_installed_apps():
		try:
			from eu_einvoice.european_e_invoice.custom.sales_invoice import attach_xml_to_pdf
			pdf_data = attach_xml_to_pdf(name, pdf_data)
		except Exception:
			msg = _("Failed to attach XML to PDF for Sales Invoice {0}").format(name)
			if show_progress:
				frappe.msgprint(msg, indicator="red", alert=True)
			frappe.log_error(title=msg)

	if show_progress:
		publish_progress(66)

	save_and_attach(pdf_data, doctype, name, target_folder, auto_name)
	frappe.log(f"PDF saved and attached successfully for {name}")

	if show_progress:
		publish_progress(100)


def create_folder(folder, parent):
	"""Make sure the folder exists and return its name."""
	new_folder_name = "/".join([parent, folder])

	if not frappe.db.exists("File", new_folder_name):
		create_new_folder(folder, parent)

	return new_folder_name


def get_pdf_data(doctype, name, print_format=None, letterhead=None):
	"""Document -> HTML -> PDF."""
	frappe.log(f"Generating HTML for {doctype} {name} with print format {print_format}")
	html = frappe.get_print(doctype, name, print_format, letterhead=letterhead)
	frappe.log(f"HTML generated for {doctype} {name}")
	pdf = get_pdf(html)
	frappe.log(f"PDF generated for {doctype} {name}")
	return pdf


def save_and_attach(content, to_doctype, to_name, folder, auto_name=None):
	"""
	Save content to disk and create a File document.

	File document is linked to another document.
	"""
	if auto_name:
		doc = frappe.get_doc(to_doctype, to_name)
		pdf_name = set_name_from_naming_options(auto_name, doc)
		file_name = "{pdf_name}.pdf".format(pdf_name=pdf_name.replace("/", "-"))
	else:
		file_name = "{to_name}.pdf".format(to_name=to_name.replace("/", "-"))

	frappe.log(f"Saving PDF as {file_name} in folder {folder}")

	file = frappe.new_doc("File")
	file.file_name = file_name
	file.content = content
	file.folder = folder
	file.is_private = 0  # Ensure the file is public
	file.attached_to_doctype = to_doctype
	file.attached_to_name = to_name
	file.save()

	frappe.log(f"File saved: {file.file_name}, Private: {file.is_private}, Folder: {file.folder}")


def set_name_from_naming_options(autoname, doc):
	"""
	Get a name based on the autoname field option
	"""
	_autoname = autoname.lower()

	if _autoname.startswith("format:"):
		return _format_autoname(autoname, doc)

	return doc.name
