# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import base64
import logging
import mimetypes
from datetime import timezone

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import extract, imap

_logger = logging.getLogger(__name__)

# Purchase orders are small; anything bigger is not one (and could be a bomb).
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def _to_naive_utc(value):
    """Odoo stores naive UTC datetimes; mail dates carry an offset that must be applied."""
    if not value:
        return False
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


class OrderkollInbox(models.Model):
    _name = "orderkoll.inbox"
    _description = "Orderkoll Inbox"
    _inherit = ["mail.thread", "mail.alias.mixin.optional"]

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        default=lambda self: self.env.user,
        help="Gets the activities: pick a customer, look at an error.",
    )
    default_pricelist_tolerance = fields.Float(
        string="Pricelist tolerance (%)",
        default=2.0,
        help="Unit price may deviate this much from the customer's pricelist "
        "before the line is flagged. 0 means: use the global Orderkoll setting "
        "(set that one to 0 for a strict check).",
    )
    auto_create_when_clean = fields.Boolean(
        help="Create the draft quotation without a click when every check passed."
    )
    price_source = fields.Selection(
        [("pricelist", "Pricelist price"), ("po", "Price on the purchase order")],
        default="pricelist",
        required=True,
        help="Unit price written on the quotation lines.",
    )
    document_ids = fields.One2many("orderkoll.document", "inbox_id")
    document_count = fields.Integer(compute="_compute_document_count")

    # IMAP intake (the mail alias arrives in a later version)
    imap_enabled = fields.Boolean(string="Fetch by IMAP")
    imap_host = fields.Char(string="IMAP server")
    imap_port = fields.Integer(string="IMAP port", default=993)
    imap_ssl = fields.Boolean(string="SSL/TLS", default=True)
    imap_user = fields.Char(string="IMAP user")
    imap_password = fields.Char(
        string="IMAP password", groups="orderkoll_core.group_orderkoll_manager"
    )
    imap_folder = fields.Char(string="IMAP folder", default="INBOX")
    imap_last_uid = fields.Integer(
        string="Last fetched UID",
        default=0,
        help="Mails with a higher IMAP UID are new. 0 means: start at the newest mail "
        "present when fetching is first enabled; older mail is never imported.",
    )
    imap_uidvalidity = fields.Integer(
        string="Mailbox UIDVALIDITY",
        readonly=True,
        help="Changes when the mailbox is recreated; the UID counter then restarts.",
    )
    imap_last_fetch = fields.Datetime(string="Last fetch", readonly=True)
    imap_last_error = fields.Text(string="Last fetch error", readonly=True)

    @api.depends("document_ids")
    def _compute_document_count(self):
        counts = {
            inbox.id: count
            for inbox, count in self.env["orderkoll.document"]._read_group(
                [("inbox_id", "in", self.ids)], ["inbox_id"], ["__count"]
            )
        }
        for inbox in self:
            inbox.document_count = counts.get(inbox.id, 0)

    # ----------------------------------------------------------- mail alias
    def _alias_get_creation_values(self):
        """Mails to the alias become documents of this inbox (Odoo's own routing)."""
        values = super()._alias_get_creation_values()
        values["alias_model_id"] = self.env["ir.model"]._get("orderkoll.document").id
        if self.id:
            import ast

            defaults = ast.literal_eval(self.alias_defaults or "{}")
            defaults["inbox_id"] = self.id
            values["alias_defaults"] = defaults
        return values

    # ------------------------------------------------------------------ IMAP
    def _imap_credentials(self):
        self.ensure_one()
        missing = [f for f in ("imap_host", "imap_user", "imap_password") if not self[f]]
        if missing:
            raise UserError(_("IMAP settings incomplete: %s", ", ".join(missing)))
        return {
            "host": self.imap_host,
            "port": self.imap_port or 993,
            "user": self.imap_user,
            "password": self.imap_password,
            "ssl": self.imap_ssl,
            "folder": self.imap_folder or "INBOX",
        }

    def action_test_imap(self):
        self.ensure_one()
        try:
            imap.fetch_new(**self._imap_credentials(), last_uid=0, limit=0)
        except Exception as exc:  # noqa: BLE001 - shown to the user as is
            raise UserError(_("IMAP connection failed: %s", exc)) from exc
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": _("IMAP login succeeded."), "type": "success"},
        }

    def fetch_mail(self, limit=50, client_factory=None):
        """Fetch new mails and turn each into a document. Returns the documents.

        One bad mail never blocks the rest: each is ingested in its own savepoint,
        failures are recorded on the inbox, and the UID pointer always advances.
        """
        documents = self.env["orderkoll.document"]
        for inbox in self:
            try:
                creds = inbox._imap_credentials()
                first_run = inbox.imap_last_uid == 0
                result = imap.fetch_new(
                    **creds,
                    last_uid=inbox.imap_last_uid,
                    limit=0 if first_run else limit,
                    max_bytes=MAX_ATTACHMENT_BYTES,
                    client_factory=client_factory,
                )
            except Exception as exc:  # noqa: BLE001 - recorded on the inbox, cron keeps going
                _logger.warning("Orderkoll inbox %s: IMAP fetch failed: %s", inbox.name, exc)
                inbox.write(
                    {"imap_last_error": str(exc)[:500], "imap_last_fetch": fields.Datetime.now()}
                )
                continue
            errors = []
            if (
                inbox.imap_uidvalidity
                and result.uidvalidity
                and result.uidvalidity != inbox.imap_uidvalidity
            ):
                errors.append(
                    f"mailbox UIDVALIDITY changed ({inbox.imap_uidvalidity} → "
                    f"{result.uidvalidity}): UID counter restarted, resuming at the newest mail"
                )
                first_run, result.mails = True, []
            if first_run:
                _logger.info(
                    "Orderkoll inbox %s: starting at UID %s", inbox.name, result.mailbox_max_uid
                )
                inbox.write(
                    {
                        "imap_last_uid": result.mailbox_max_uid,
                        "imap_uidvalidity": result.uidvalidity or inbox.imap_uidvalidity,
                        "imap_last_error": "; ".join(errors) or False,
                        "imap_last_fetch": fields.Datetime.now(),
                    }
                )
                continue
            for uid, size in result.skipped:
                errors.append(
                    "uid %s skipped: %d bytes is over the %d MB cap"
                    % (uid, size, MAX_ATTACHMENT_BYTES // (1024 * 1024))
                )
            for mail in result.mails:
                try:
                    with self.env.cr.savepoint():
                        documents |= inbox._ingest_mail(mail)
                except Exception as exc:  # noqa: BLE001 - one bad mail must not block the rest
                    _logger.exception(
                        "Orderkoll inbox %s: mail uid %s could not be ingested",
                        inbox.name,
                        mail.uid,
                    )
                    errors.append(
                        f"uid {mail.uid} ({mail.subject[:40]}) not ingested: {str(exc)[:120]}"
                    )
            inbox.write(
                {
                    "imap_last_uid": max(inbox.imap_last_uid, result.max_uid),
                    "imap_uidvalidity": result.uidvalidity or inbox.imap_uidvalidity,
                    "imap_last_error": "; ".join(errors)[:2000] or False,
                    "imap_last_fetch": fields.Datetime.now(),
                }
            )
        return documents

    @api.model
    def _cron_fetch_all(self):
        documents = self.search([("imap_enabled", "=", True)]).fetch_mail()
        if documents:
            self.env["orderkoll.document"]._trigger_processing()

    # ---------------------------------------------------------------- ingest
    def _ingest_mail(self, mail):
        """One document per mail: the first PO-like attachment is the main one,
        the others are extra; no PO attachment means the body is the order."""
        self.ensure_one()
        Document = self.env["orderkoll.document"]
        if mail.message_id and Document.search_count(
            [("inbox_id", "=", self.id), ("email_message_id", "=", mail.message_id)]
        ):
            _logger.info("Orderkoll: mail %s already ingested, skipped", mail.message_id)
            return Document
        sender = (mail.sender_email or "").lower()
        values = {
            "inbox_id": self.id,
            "sender_email": sender,
            "sender_name": mail.sender_name,
            "sender_domain": sender.rsplit("@", 1)[-1] if "@" in sender else False,
            "email_subject": mail.subject,
            "email_message_id": mail.message_id or False,
            "email_date": _to_naive_utc(mail.date),
            "email_body": mail.body_text
            or (extract.html_to_text(mail.body_html) if mail.body_html else ""),
            "imap_uid": mail.uid,
        }
        main, extras = None, []
        for attachment in mail.attachments:
            if len(attachment.data) > MAX_ATTACHMENT_BYTES:
                _logger.warning(
                    "Orderkoll: attachment %s (%d bytes) skipped, over the size cap",
                    attachment.name,
                    len(attachment.data),
                )
                continue
            source_type = extract.detect_source_type(attachment.name, attachment.mimetype)
            if source_type and main is None:
                main = (attachment, source_type)
            else:
                extras.append(attachment)
        values["source_type"] = main[1] if main else "email_body"
        document = Document.create(values)
        if main:
            attachment = self._make_attachment(document, main[0])
            # main attachment: shown beside the form on wide screens
            document.write(
                {"attachment_id": attachment.id, "message_main_attachment_id": attachment.id}
            )
        document.extra_attachment_ids = [(4, self._make_attachment(document, a).id) for a in extras]
        return document

    @api.model
    def _fetched_mail_from_msg_dict(self, msg_dict):
        """Odoo's parsed incoming mail → the same FetchedMail the IMAP path uses."""
        from email.utils import parseaddr, parsedate_to_datetime

        name, addr = parseaddr(msg_dict.get("from") or msg_dict.get("email_from") or "")
        date = None
        if msg_dict.get("date"):
            try:
                date = parsedate_to_datetime(str(msg_dict["date"]))
            except (TypeError, ValueError):
                date = None
        attachments = []
        for att in msg_dict.get("attachments") or []:
            fname, content = att[0], att[1]
            if isinstance(content, str):
                content = content.encode("utf-8", errors="replace")
            mimetype = mimetypes.guess_type(fname or "")[0] or "application/octet-stream"
            attachments.append(imap.Attachment(fname or "attachment", content or b"", mimetype))
        body_html = msg_dict.get("body") or ""
        return imap.FetchedMail(
            uid=0,
            message_id=(msg_dict.get("message_id") or "").strip(),
            sender_email=addr.lower(),
            sender_name=name.strip(),
            subject=msg_dict.get("subject") or "",
            date=date,
            body_text=extract.html_to_text(body_html) if body_html else "",
            body_html=body_html,
            attachments=attachments,
        )

    # Only types the intake understands or that a browser cannot execute are kept;
    # everything else (html, svg, xml, scripts, unknown) is stored as a plain binary.
    SAFE_MIMETYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "text/csv",
        "text/plain",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/tiff",
        "image/bmp",
        "application/octet-stream",
    }

    @classmethod
    def _safe_mimetype(cls, mimetype, name=""):
        mimetype = (mimetype or "").split(";")[0].strip().lower()
        name = (name or "").strip().rstrip(". ")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in ("html", "htm", "xhtml", "svg", "xml", "xsl", "xslt", "js", "mjs"):
            return "application/octet-stream"
        return mimetype if mimetype in cls.SAFE_MIMETYPES else "application/octet-stream"

    def _make_attachment(self, document, attachment):
        # attachments_mime_plainxml: Odoo re-sniffs generic binaries and stores anything
        # html/xml/svg-like as text/plain, whatever user runs the intake.
        record = (
            self.env["ir.attachment"]
            .with_context(attachments_mime_plainxml=True)
            .create(
                {
                    "name": attachment.name,
                    "datas": base64.b64encode(attachment.data),
                    "mimetype": self._safe_mimetype(attachment.mimetype, attachment.name),
                    "res_model": document._name,
                    "res_id": document.id,
                }
            )
        )
        # Belt and braces: whatever Odoo sniffed, never keep a browser-renderable type.
        stored = (record.mimetype or "").lower()
        if any(k in stored for k in ("ht", "xml", "svg", "script")):
            record.write({"mimetype": "text/plain"})
        return record

    def action_open_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Documents"),
            "res_model": "orderkoll.document",
            "view_mode": "list,form",
            "domain": [("inbox_id", "=", self.id)],
            "context": {"default_inbox_id": self.id},
        }
