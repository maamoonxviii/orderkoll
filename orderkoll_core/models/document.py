# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import base64
import logging

import psycopg2
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, email_normalize

from ..services import alerts, extract, match
from ..services.errors import TransientProcessingError

MAX_RETRIES = 3

_logger = logging.getLogger(__name__)

STATES = [
    ("new", "New"),
    ("extracting", "Extracting"),
    ("needs_review", "Needs review"),
    ("ready", "Ready"),
    ("created", "Quotation created"),
    ("rejected", "Rejected"),
    ("error", "Error"),
]


class OrderkollDocument(models.Model):
    _name = "orderkoll.document"
    _description = "Orderkoll Document"
    _inherit = ["mail.thread.main.attachment", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    inbox_id = fields.Many2one("orderkoll.inbox", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", related="inbox_id.company_id", store=True)
    state = fields.Selection(STATES, default="new", required=True, tracking=True, index=True)

    # sender
    sender_email = fields.Char(index=True)
    sender_name = fields.Char()
    sender_domain = fields.Char(index=True)
    partner_id = fields.Many2one("res.partner", string="Customer", tracking=True)
    partner_resolution = fields.Selection(
        [
            ("email", "Sender email"),
            ("domain", "Sender domain"),
            ("manual", "Picked manually"),
            ("none", "Not resolved"),
        ],
        default="none",
    )

    # mail and files
    email_subject = fields.Char()
    email_message_id = fields.Char(index=True)
    email_date = fields.Datetime()
    email_body = fields.Text()
    imap_uid = fields.Integer()
    attachment_id = fields.Many2one(
        "ir.attachment", string="Main attachment", ondelete="set null", readonly=True
    )
    attachment_datas = fields.Binary(
        related="attachment_id.datas", string="File", compute_sudo=False
    )
    attachment_name = fields.Char(
        related="attachment_id.name", string="File name", compute_sudo=False
    )
    extra_attachment_ids = fields.Many2many(
        "ir.attachment", "orderkoll_document_extra_attachment_rel", string="Other attachments"
    )
    source_type = fields.Selection(
        [("pdf", "PDF"), ("xlsx", "Excel"), ("csv", "CSV"), ("email_body", "Email body")],
        required=True,
    )
    raw_text = fields.Text(help="Text extracted from the document before any AI step.")
    extraction_method = fields.Char(help="pdfplumber, pypdf, openpyxl, csv, email or none (scan).")

    # extraction result (filled by the extraction engine)
    extraction_json = fields.Text()
    llm_provider = fields.Char()
    llm_model = fields.Char()
    llm_raw_response = fields.Text()
    extraction_ms = fields.Integer(string="Extraction time (ms)")

    # parsed header
    po_number = fields.Char(string="PO number", index=True)
    po_date = fields.Date(string="PO date")
    requested_date = fields.Date(string="Requested date")
    currency_id = fields.Many2one("res.currency")
    document_total = fields.Float()
    lines_total = fields.Float()
    totals_ok = fields.Boolean()
    totals_checked = fields.Boolean(
        help="False when the document prints no amount to compare the lines with."
    )
    duplicate_of_id = fields.Many2one("orderkoll.document", string="Duplicate of")

    line_ids = fields.One2many("orderkoll.line", "document_id")
    line_count = fields.Integer(compute="_compute_line_count")
    sale_order_id = fields.Many2one("sale.order", string="Quotation", readonly=True)
    checks_log = fields.Text(help="One line per check that ran and its result.")
    error_message = fields.Text()
    retry_count = fields.Integer(default=0, help="Transient failures so far (rate limit, timeout).")

    # review
    scan_checked = fields.Boolean(
        string="Scan checked by a person",
        readonly=True,
        help="Set with the 'Mark scan as checked' button once someone compared an OCR-read "
        "document with the PDF.",
    )
    reject_reason = fields.Text(readonly=True)
    review_todo = fields.Html(
        string="To do",
        compute="_compute_review_todo",
        sanitize=True,
        help="Plain-language list of what keeps this document from becoming a quotation.",
    )

    # Header fields whose manual edit re-runs the checks (Pro adds its own).
    _RECHECK_FIELDS = ("document_total", "po_number")

    @api.depends("po_number", "sender_email", "attachment_id.name", "email_subject")
    def _compute_name(self):
        for doc in self:
            doc.name = (
                doc.po_number
                or doc.attachment_id.name
                or doc.email_subject
                or (doc.sender_email or _("Document"))
            )

    @api.constrains("attachment_id", "extra_attachment_ids")
    def _check_attachments_belong_to_document(self):
        """Only attachments stored on this document may be linked: no reading
        other records' files through the related binary field."""
        for doc in self:
            for attachment in doc.attachment_id | doc.extra_attachment_ids:
                if attachment.res_model != doc._name or attachment.res_id != doc.id:
                    raise ValidationError(
                        _("Attachment %s does not belong to this document.", attachment.name)
                    )

    def write(self, vals):
        """State changes trigger their follow-ups (ready → hook, error → task + alert,
        processed after a failure → that task closed); a person editing a document under
        review gets the checks re-run at once."""
        new_state = vals.get("state")
        entering = (
            self.filtered(lambda d: d.state != new_state)
            if new_state in ("needs_review", "ready", "error")
            else self.browse()
        )
        res = super().write(vals)
        for doc in entering:
            if new_state == "error":
                doc._on_error()
                continue
            doc._close_task("Processing failed", _("Processed successfully on a later run."))
            if new_state == "ready":
                doc._orderkoll_on_ready()
        if self.env.context.get("orderkoll_no_recheck"):
            return res
        under_review = self.filtered(lambda d: d.state in ("needs_review", "ready"))
        if "partner_id" in vals:
            with_partner = under_review.filtered("partner_id")
            with_partner.with_context(orderkoll_no_recheck=True).write(
                {"partner_resolution": "manual"}
            )
            with_partner._recheck(_("customer changed"), rematch=True)
        elif set(vals) & set(self._RECHECK_FIELDS):
            under_review._recheck(_("document edited"))
        return res

    @api.depends("line_ids")
    def _compute_line_count(self):
        for doc in self:
            doc.line_count = len(doc.line_ids)

    # ------------------------------------------------------------ mail alias
    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Called by Odoo's mail routing for a mail sent to an inbox alias."""
        inbox_id = (custom_values or {}).get("inbox_id")
        inbox = (
            self.env["orderkoll.inbox"].browse(inbox_id)
            if inbox_id
            else self.env["orderkoll.inbox"]
        )
        if not inbox.exists():
            raise ValueError(_("Alias has no Orderkoll inbox in its defaults"))
        mail = inbox._fetched_mail_from_msg_dict(msg_dict)
        document = inbox._ingest_mail(mail)
        if not document:
            # Duplicate Message-ID: never route it onto an existing document (the From
            # header is spoofable). Odoo's gateway normally drops these before we see them.
            raise ValueError(_("Mail refused: Message-ID already received"))
        # The document holds sanitised copies of the attachments; the gateway must not
        # post the originals (browser-renderable types) on the record as well.
        msg_dict["attachments"] = []
        self._trigger_processing()
        return document

    def message_update(self, msg_dict, update_vals=None):
        """A reply on a document's thread is just a chatter message; nothing to change.
        Its attachments get the same treatment as new mail: sanitised copies on the
        document, never the originals (browser-renderable types) on the message."""
        for document in self:
            mail = document.inbox_id._fetched_mail_from_msg_dict(msg_dict)
            for attachment in mail.attachments:
                document.inbox_id._make_attachment(document, attachment)
        msg_dict["attachments"] = []
        return True

    # ------------------------------------------------------------- checks log
    CHECK_MARKS = {"ok": "[OK]", "flag": "[FLAG]", "info": "[INFO]"}

    def _log_check(self, name, result, status="info"):
        """One line per check: ``[OK]`` passed, ``[FLAG]`` needs a person, ``[INFO]`` context.
        The same lines are posted to the chatter after each processing run and, later,
        to the quotation."""
        self.ensure_one()
        line = f"{self.CHECK_MARKS.get(status, '[INFO]')} {name}: {result}"
        self.checks_log = f"{self.checks_log}\n{line}" if self.checks_log else line

    def _post_system_note(self, body):
        """Orderkoll's own notes are posted as the system user (the person who acted is
        named in the text): works for users without an email address and for the cron."""
        self.ensure_one()
        return self.message_post(
            body=body,
            message_type="notification",
            author_id=self.env.ref("base.partner_root").id,
        )

    def _check_lines(self):
        return [ln for ln in (self.checks_log or "").split("\n") if ln.strip()]

    def _post_checks_summary(self, start=0, title=None):
        """One chatter message per processing run (or re-check) listing every check
        that ran in it; ``start`` skips the lines of earlier runs."""
        self.ensure_one()
        lines = self._check_lines()[start:]
        if not lines:
            return
        flags = sum(1 for ln in lines if ln.startswith("[FLAG]"))
        oks = sum(1 for ln in lines if ln.startswith("[OK]"))
        items = "".join(f"<li>{escape(ln)}</li>" for ln in lines)
        title = escape(
            _(
                "%(title)s: %(ok)s passed, %(flags)s flagged → %(state)s",
                title=title or _("Checks"),
                ok=oks,
                flags=flags,
                state=dict(STATES).get(self.state, self.state),
            )
        )
        self._post_system_note(Markup(f"<p><b>{title}</b></p><ul>{items}</ul>"))

    # ------------------------------------------------------------ processing
    def action_process(self):
        """new → extracting → text → engine hook → needs_review / ready.

        Each document runs in its own savepoint: a failure leaves no half-written
        state. Transient failures keep the document `new` for the cron to retry.
        """
        for doc in self:
            try:
                with self.env.cr.savepoint():
                    doc.write({"state": "extracting", "error_message": False, "checks_log": False})
                    doc._run_pipeline()
                    doc._post_checks_summary()
                    if doc.state == "ready" and doc.inbox_id.auto_create_when_clean:
                        doc._create_quotation()
            except TransientProcessingError as exc:
                retries = doc.retry_count + 1
                if retries >= MAX_RETRIES:
                    _logger.warning(
                        "Orderkoll document %s: giving up after %s transient failures",
                        doc.id,
                        retries,
                    )
                    doc.write(
                        {
                            "state": "error",
                            "retry_count": retries,
                            "error_message": _(
                                "Gave up after %(n)s attempts: %(err)s", n=retries, err=exc
                            ),
                        }
                    )
                else:
                    _logger.info(
                        "Orderkoll document %s: transient failure %s, will retry: %s",
                        doc.id,
                        retries,
                        exc,
                    )
                    doc.write(
                        {
                            "state": "new",
                            "retry_count": retries,
                            "error_message": _(
                                "Attempt %(n)s failed, will retry: %(err)s", n=retries, err=exc
                            ),
                        }
                    )
            except psycopg2.extensions.TransactionRollbackError:
                # Another worker (the cron, a second click) changed this document at the same
                # time. The transaction is lost: let Odoo retry the whole call.
                raise
            except Exception as exc:  # noqa: BLE001 - every failure is stored, never lost
                _logger.exception("Orderkoll document %s failed", doc.id)
                doc.write({"state": "error", "error_message": str(exc)})
        return True

    def _run_pipeline(self):
        """Text → customer → lines (engine) → matching and checks → state."""
        self.ensure_one()
        self._extract_text()
        self._resolve_partner()
        if not self.raw_text:
            if extract.ocr_available():
                reason = "no text layer (scan) and OCR found nothing readable"
            else:
                reason = "no text layer (scan); OCR not installed (tesseract)"
            self._log_check("text extraction", reason, "flag")
            self.state = "needs_review"
            return
        if not self._extract_lines():
            self._log_check(
                "extraction engine", "not installed; lines must be entered by hand", "flag"
            )
            self.state = "needs_review"
            return
        self._after_lines_extracted()

    def _extract_text(self):
        self.ensure_one()
        if self.source_type == "email_body":
            text, method = extract.clean_email_body(self.email_body or ""), "email"
        else:
            if not self.attachment_id:
                raise ValueError(_("No attachment on this document"))
            data = base64.b64decode(self.attachment_id.datas or b"")
            text, method = extract.extract_text(self.source_type, data)
        self.write({"raw_text": text, "extraction_method": method})
        note = " (scanned PDF, OCR)" if method == "ocr" else ""
        self._log_check("text extraction", f"{method}, {len(text)} characters{note}")

    # ---------------------------------------------------------- customer
    def _resolve_partner(self):
        """Sender email exact → sender domain (never a webmail domain) → manual pick.
        The company (commercial partner) is stored, never the contact."""
        self.ensure_one()
        Partner = self.env["res.partner"]
        # Normalised and compared with "=": the address is never used as a LIKE pattern.
        email = email_normalize(self.sender_email or "", strict=True) or ""
        domain = match.domain_of(email)
        ignored = match.parse_ignored_domains(
            self.env["ir.config_parameter"].sudo().get_param("orderkoll.ignored_domains")
        )
        partner, how, why = Partner, "none", "no valid sender address"
        if email:
            contact = Partner.search(
                self._partner_company_domain() + [("email_normalized", "=", email)], limit=1
            )
            if contact:
                partner, how, why = contact.commercial_partner_id, "email", email
            elif match.is_ignored_domain(domain, ignored):
                why = f"webmail domain {domain}"
            else:
                companies = self._partners_for_domain(domain)
                if len(companies) == 1:
                    partner, how, why = companies, "domain", domain
                elif companies:
                    why = f"{len(companies)} customers share the domain {domain}"
                else:
                    why = f"no customer with the domain {domain}"
        self.write({"partner_id": partner.id, "partner_resolution": how})
        if partner:
            self._log_check("customer", f"{how} {why} → {partner.display_name}", "ok")
        else:
            self._log_check("customer", f"not resolved ({why})", "flag")
            self._schedule_pick_customer()
        return partner

    def _partner_company_domain(self):
        """Partners of the document's company or shared ones; never another company's."""
        return ["|", ("company_id", "=", False), ("company_id", "=", self.company_id.id)]

    def _partners_for_domain(self, domain):
        """Companies whose own website/email domain, or a contact's email domain, is ``domain``."""
        Partner = self.env["res.partner"]
        if not domain or not match.is_plain_domain(domain):
            return Partner
        candidates = Partner.search(
            self._partner_company_domain()
            + ["|", ("website", "ilike", domain), ("email_normalized", "=like", f"%@{domain}")]
        )
        exact = candidates.filtered(
            lambda p: match.website_domain(p.website) == domain
            or match.domain_of(p.email) == domain
        )
        return exact.mapped("commercial_partner_id")

    def _schedule_pick_customer(self):
        self._schedule_task(
            "Pick customer",
            _("The sender %s could not be matched to a customer.", self.sender_email or "?"),
        )

    def _schedule_task(self, summary, note):
        """A to-do for the inbox's responsible person (never the system user); one per
        summary while it is open."""
        self.ensure_one()
        if self.activity_ids.filtered(lambda a: a.summary == summary):
            return
        user = self.inbox_id.user_id or self.env.user
        if user._is_superuser():  # gateway/cron context: never assign work to OdooBot
            user = self.env.ref("base.user_admin")
        self.activity_schedule(
            "mail.mail_activity_data_todo", summary=summary, note=note, user_id=user.id
        )

    def _close_task(self, summary, feedback):
        """Marks this document's open to-do done once its cause is gone."""
        self.ensure_one()
        tasks = self.activity_ids.filtered(lambda a: a.summary == summary)
        if tasks:
            tasks.action_feedback(feedback=feedback)

    # ------------------------------------------------------- state follow-ups
    def _orderkoll_on_ready(self):
        """Hook: called once each time a document becomes ready (every check passed).
        Core does nothing here; Orderkoll Tier Glue and other add-ons subscribe to it."""
        self.ensure_one()

    def _on_error(self):
        """Processing failed: a task for the responsible person and, if configured,
        an alert. The alert carries no document content, only where to look."""
        self.ensure_one()
        first_line = (self.error_message or "").strip().split("\n")[0][:200]
        self._schedule_task(
            "Processing failed",
            _("Orderkoll could not process this document: %s", first_line or "?"),
        )
        self._send_alert(
            _(
                "Orderkoll: document #%(id)s in inbox '%(inbox)s' failed and needs a "
                "look.\n%(url)s",
                id=self.id,
                inbox=self.inbox_id.name,
                url=self._document_url(),
            )
        )

    def _document_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        return f"{base}/odoo/action-orderkoll_core.action_document/{self.id}"

    def _send_alert(self, text):
        if config["test_enable"]:
            return False  # never message a real chat from a test run
        params = self.env["ir.config_parameter"].sudo()
        sent = alerts.send_telegram(
            params.get_param("orderkoll.alert_telegram_token"),
            params.get_param("orderkoll.alert_telegram_chat"),
            text,
        )
        hook = params.get_param("orderkoll.alert_webhook_url")
        if hook:
            sent = (
                alerts.send_webhook(
                    hook, {"event": "document_error", "document_id": self.id, "text": text}
                )
                or sent
            )
        return sent

    def action_open_pick_partner(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Pick customer"),
            "res_model": "orderkoll.pick_partner",
            "view_mode": "form",
            "target": "new",
            "context": {"default_document_id": self.id},
        }

    def _after_partner_picked(self):
        """Once the customer is known, the code memory applies: match again and decide."""
        self.ensure_one()
        if self.line_ids:
            self._recheck(_("customer picked"), rematch=True)

    # --------------------------------------------------------------- review
    def _recheck(self, reason, rematch=False):
        """Re-run matching status and every check after a person changed something;
        the run is logged and posted like a processing run. Only documents under
        review are touched: a created or rejected document never changes state."""
        for doc in self.with_context(orderkoll_no_recheck=True):
            if doc.state not in ("needs_review", "ready"):
                continue
            start = len(doc._check_lines())
            doc._log_check("re-check", f"{reason} (by {self.env.user.name})")
            if rematch:
                doc._match_lines()
            else:
                doc._log_products_status()
            doc._decide_state()
            doc._post_checks_summary(start=start, title=_("Re-check"))
        return True

    def _log_products_status(self):
        missing = self.line_ids.filtered(lambda ln: not ln.product_id)
        if missing:
            codes = ", ".join(ln.customer_code or f"'{ln.description}'" for ln in missing)
            self._log_check(
                "products",
                f"{len(missing)}/{len(self.line_ids)} without a product: {codes}",
                "flag",
            )
        else:
            self._log_check("products", f"all {len(self.line_ids)} lines have a product", "ok")

    def action_recheck(self):
        self._recheck(_("Re-check clicked"))
        return True

    def action_mark_scan_checked(self):
        for doc in self.filtered(lambda d: d.state == "needs_review"):
            doc.with_context(orderkoll_no_recheck=True).write({"scan_checked": True})
            doc._recheck(_("scan marked as checked"))
        return True

    def action_reject(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject document"),
            "res_model": "orderkoll.reject",
            "view_mode": "form",
            "target": "new",
            "context": {"default_document_ids": self.ids},
        }

    def _reject(self, reason):
        """Reject with a reason (required): state, reason, chatter, open activities closed.
        Used by the Reject button and, later, by the approval channel."""
        reason = (reason or "").strip()
        if not reason:
            raise UserError(_("Please give a reason for rejecting."))
        for doc in self.with_context(orderkoll_no_recheck=True):
            if doc.state == "created":
                raise UserError(
                    _("%s already became a quotation; cancel the quotation instead.", doc.name)
                )
            doc.write({"state": "rejected", "reject_reason": reason})
            doc.activity_ids.unlink()
            doc._post_system_note(
                _(
                    "Rejected by %(user)s. Reason: %(reason)s",
                    user=self.env.user.name,
                    reason=reason,
                )
            )
        return True

    def _review_todo_items(self):
        """What a person still has to do, in plain words. Orderkoll Pro adds its checks."""
        self.ensure_one()
        items = []
        if not self.raw_text and self.state == "needs_review":
            if self.source_type == "pdf" and not extract.ocr_available():
                items.append(
                    _(
                        "No text could be read: this PDF looks like a scan, and the scan reader "
                        "(OCR) is not installed on this Odoo server (see the install guide). "
                        "Enter the lines by hand or reject it."
                    )
                )
            else:
                items.append(
                    _("No text could be read from the file. Enter the lines by hand or reject it.")
                )
        if not self.partner_id:
            items.append(
                _(
                    "Pick the customer: no customer in Odoo matches the sender %s.",
                    self.sender_email or "?",
                )
            )
        if self.raw_text and not self.line_ids:
            items.append(
                _("No order lines were read. Add them by hand or click Re-run extraction.")
            )
        missing = self.line_ids.filtered(lambda ln: not ln.product_id)
        if missing:
            codes = ", ".join(ln.customer_code or ln.description or "?" for ln in missing)
            items.append(
                _(
                    "Map %(n)s line(s) to a product: click Map on each yellow line (%(codes)s).",
                    n=len(missing),
                    codes=codes,
                )
            )
        if self.extraction_method == "ocr" and not self.scan_checked:
            items.append(
                _(
                    "This is a scanned PDF read by OCR: compare quantities and prices with the "
                    "PDF, then click Mark scan as checked."
                )
            )
        return items

    @api.depends(
        "state", "partner_id", "line_ids.product_id", "scan_checked", "raw_text", "totals_ok"
    )
    def _compute_review_todo(self):
        for doc in self:
            items = doc._review_todo_items() if doc.state == "needs_review" else []
            doc.review_todo = (
                Markup("<ul class='mb-0'>%s</ul>")
                % Markup("").join(Markup("<li>%s</li>") % item for item in items)
                if items
                else False
            )

    def _extract_lines(self):
        """Hook for the extraction engine (Orderkoll Pro). Core has none: returns False."""
        self.ensure_one()
        return False

    def _after_lines_extracted(self):
        """Match every line to a product, then run the checks (Pro) and decide."""
        self.ensure_one()
        self._match_lines()
        self._decide_state()

    def _decide_state(self):
        """needs_review when the customer is unknown or any line is unmatched;
        otherwise ready. Orderkoll Pro extends this with its checks."""
        self.ensure_one()
        unmatched = self.line_ids.filtered(lambda ln: not ln.product_id)
        if not self.partner_id or unmatched or not self.line_ids or self._ocr_needs_review():
            self.state = "needs_review"
        else:
            self.state = "ready"

    def _ocr_needs_review(self):
        """OCR text is never trusted blindly: a scanned PO always gets a human look."""
        self.ensure_one()
        if self.extraction_method != "ocr":
            return False
        if self.scan_checked:
            self._log_check("review", "scanned PDF compared with the file by a person", "ok")
            return False
        self._log_check("review", "scanned PDF read by OCR: verify quantities and prices", "flag")
        return True

    # ---------------------------------------------------------- products
    def _match_lines(self):
        """Per-customer code memory → internal reference → barcode → name similarity
        (the customer's recent products first, then every sale-able product).
        Written in core from scratch; nothing here depends on OCA modules."""
        self.ensure_one()
        params = self.env["ir.config_parameter"].sudo()
        threshold = float(params.get_param("orderkoll.fuzzy_threshold") or 0.88)
        memory = self._code_memory()
        catalogue = recent = None  # loaded only when a name match is needed
        matched = []
        unknown = []
        for line in self.line_ids:
            if line.match_method == "manual" and line.product_id:
                matched.append(line)  # a person's pick is never overwritten
                continue
            product, method, score = self._match_one(line, memory)
            if not product and line.description:
                if catalogue is None:
                    catalogue, recent = self._name_catalogue()
                product, score = self._match_by_name(line.description, catalogue, recent, threshold)
                method = "fuzzy" if product else "none"
            line.with_context(orderkoll_no_recheck=True).write(
                {
                    "product_id": product.id if product else False,
                    "match_method": method,
                    "match_score": score,
                    "status": "matched" if product else "needs_mapping",
                }
            )
            (matched if product else unknown).append(line)
        summary = f"{len(matched)}/{len(self.line_ids)} matched"
        if unknown:
            summary += "; unknown: " + ", ".join(
                ln.customer_code or f"'{ln.description}'" for ln in unknown
            )
        self._log_check("products", summary, "flag" if unknown else "ok")
        return not unknown

    def _code_memory(self):
        if not self.partner_id:
            return {}
        rows = self.env["orderkoll.sku_map"].search(
            self._company_domain() + [("partner_id", "=", self.partner_id.commercial_partner_id.id)]
        )
        return {row.customer_code: row for row in rows}

    def _match_one(self, line, memory):
        """Code-based steps; returns (product, method, score)."""
        Product = self.env["product.product"]
        code = match.normalize_code(line.customer_code)
        if not code:
            return Product, "none", 0.0
        row = memory.get(code)
        if row:
            row.hit_count += 1
            return row.product_id, "sku_map", 1.0
        compact = match.compact_code(code)
        base = self._company_domain() + [("sale_ok", "=", True)]
        product = Product.search(
            base + [("default_code", "=ilike", self._escape_like(code))], limit=1
        )
        if not product and compact:
            product = Product.search(base + [("default_code", "!=", False)]).filtered(
                lambda p: match.compact_code(p.default_code) == compact
            )[:1]
        if product:
            return product, "default_code", 1.0
        product = Product.search(base + [("barcode", "=", code)], limit=1) or (
            Product.search(base + [("barcode", "=", compact)], limit=1) if compact else Product
        )
        if product:
            return product, "barcode", 1.0
        return Product, "none", 0.0

    def _company_domain(self):
        """Records of the document's company or shared ones (the cron runs as superuser,
        so record rules do not apply: the scope must be explicit)."""
        return ["|", ("company_id", "=", False), ("company_id", "=", self.company_id.id)]

    @staticmethod
    def _escape_like(value):
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _name_catalogue(self):
        """([(id, name)] of all sale-able products, set of ids recently sold to the customer)."""
        products = self.env["product.product"].search_read(
            self._company_domain() + [("sale_ok", "=", True)], ["name"]
        )
        catalogue = [(p["id"], p["name"]) for p in products]
        recent = set()
        if self.partner_id:
            since = fields.Date.subtract(fields.Date.today(), days=365)
            lines = self.env["sale.order.line"].search_read(
                [
                    ("company_id", "=", self.company_id.id),
                    ("order_partner_id", "child_of", self.partner_id.commercial_partner_id.id),
                    ("create_date", ">=", fields.Datetime.to_string(since)),
                ],
                ["product_id"],
            )
            recent = {ln["product_id"][0] for ln in lines if ln["product_id"]}
            recent |= {row.product_id.id for row in self._code_memory().values()}
        return catalogue, recent

    def _match_by_name(self, description, catalogue, recent, threshold):
        Product = self.env["product.product"]
        if recent:
            pid, score = match.best_name_match(
                description, [c for c in catalogue if c[0] in recent], threshold
            )
            if pid:
                return Product.browse(pid), score
        pid, score = match.best_name_match(description, catalogue, threshold)
        return (Product.browse(pid) if pid else Product), score

    @api.model
    def _cron_process_pending(self, limit=20):
        """One document per commit: a slow provider never rolls back the whole batch."""
        for doc in self.search([("state", "=", "new")], limit=limit, order="id"):
            doc.action_process()
            if not config["test_enable"]:  # a test transaction must not be committed
                self.env.cr.commit()  # pylint: disable=invalid-commit
        self._ping_heartbeat()

    @api.model
    def _ping_heartbeat(self):
        """Dead-man switch: the monitor alerts when these pings stop (cron down)."""
        if config["test_enable"]:
            return False
        url = self.env["ir.config_parameter"].sudo().get_param("orderkoll.heartbeat_url")
        return alerts.ping(url)

    @api.model
    def _trigger_processing(self):
        """Start the processing cron now instead of at its next 2-minute slot."""
        cron = self.env.ref("orderkoll_core.cron_process_pending", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    def action_rerun_extraction(self):
        return self.action_process()
