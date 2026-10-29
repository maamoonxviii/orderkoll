# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import unittest
from email.message import EmailMessage

try:
    from ._services import DATA, imap
except ImportError:  # unittest discovery rooted at tests/ (no Odoo)
    from _services import DATA, imap


class TestParseMessage(unittest.TestCase):
    def test_plain_text_order_mail(self):
        mail = imap.parse_message((DATA / "eml-1.eml").read_bytes(), uid=7)
        self.assertEqual(mail.uid, 7)
        self.assertEqual(mail.sender_email, "j.hartley@albiontools.example")
        self.assertEqual(mail.sender_name, "James Hartley")
        self.assertEqual(mail.subject, "Purchase order AT/2026/0318 - Albion Tools Ltd")
        self.assertTrue(mail.message_id.startswith("<") and mail.message_id.endswith(">"))
        self.assertIn("AT/2026/0318", mail.body_text)
        self.assertIn("AT-24286", mail.body_text)
        self.assertEqual(mail.attachments, [])
        self.assertEqual(mail.date.isoformat(), "2026-10-04T09:30:00+02:00")

    def test_multipart_alternative_keeps_plain_and_html(self):
        mail = imap.parse_message((DATA / "eml-5.eml").read_bytes(), uid=1)
        self.assertEqual(mail.sender_email, "k.vogel@rheinwerk-technik.example")
        self.assertIn("4500000929", mail.body_text)
        self.assertIn("<p>", mail.body_html)

    def test_pdf_attachment_is_extracted_with_name_and_mimetype(self):
        pdf = (DATA / "pdf-L01-1.pdf").read_bytes()
        msg = EmailMessage()
        msg["From"] = "Inköp <INKOP@NordicFasteners.example>"
        msg["To"] = "orders@orderkoll-demo.example"
        msg["Subject"] = "PO-2026-00364"
        msg["Message-ID"] = "<abc@nordicfasteners.example>"
        msg.set_content("Please see attached.")
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="PO-2026-00364.pdf")
        msg.add_attachment(b"\x89PNG", maintype="image", subtype="png", filename="logo.png")
        mail = imap.parse_message(msg.as_bytes(), uid=3)
        self.assertEqual(mail.sender_email, "inkop@nordicfasteners.example")  # lower-cased
        self.assertEqual(mail.body_text.strip(), "Please see attached.")
        self.assertEqual([a.name for a in mail.attachments], ["PO-2026-00364.pdf", "logo.png"])
        self.assertEqual(mail.attachments[0].mimetype, "application/pdf")
        self.assertEqual(mail.attachments[0].data, pdf)

    def test_unknown_charset_falls_back_instead_of_raising(self):
        raw = (
            b"From: a@x.example\r\nSubject: PO 5\r\n"
            b"Content-Type: text/plain; charset=x-unknown-foo\r\n\r\n10 x A-1 \xe4\r\n"
        )
        mail = imap.parse_message(raw, uid=5)
        self.assertIn("10 x A-1", mail.body_text)

    def test_missing_headers_do_not_crash(self):
        mail = imap.parse_message(b"Subject: hi\r\n\r\nbody only\r\n", uid=9)
        self.assertEqual(mail.sender_email, "")
        self.assertEqual(mail.message_id, "")
        self.assertEqual(mail.body_text.strip(), "body only")
        self.assertIsNone(mail.date)


class FakeImap:
    """Stands in for imaplib.IMAP4_SSL: three messages with uids 4, 9, 12."""

    def __init__(self, host, port):
        self.calls = []
        self.store = {
            4: self._raw("a@x.com", "PO 4"),
            9: self._raw("b@y.com", "PO 9"),
            12: self._raw("c@z.com", "PO 12"),
        }

    @staticmethod
    def _raw(sender, subject):
        msg_id = subject.replace(" ", "")
        return (
            f"From: {sender}\r\nSubject: {subject}\r\nMessage-ID: <{msg_id}@t>\r\n\r\n"
            f"body {subject}\r\n"
        ).encode()

    def login(self, user, password):
        self.calls.append(("login", user))
        return "OK", []

    uidvalidity = b"1700000000"

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        if folder != "INBOX":
            return "NO", [b"Mailbox doesn't exist"]
        return "OK", [b"3"]

    def response(self, code):
        return "OK", [self.uidvalidity] if code == "UIDVALIDITY" else [None]

    def uid(self, command, *args):
        self.calls.append(("uid", command, args))
        if command == "SEARCH":
            lo = (
                int(args[-1].split(":")[0].replace("UID", "").strip("() "))
                if "UID" in args[-1]
                else 1
            )
            uids = [u for u in sorted(self.store) if u >= lo]
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if command == "FETCH" and args[1] == "(RFC822.SIZE)":
            u = int(args[0])
            return "OK", [f"{u} (UID {u} RFC822.SIZE {len(self.store[u])})".encode()]
        if command == "FETCH":
            u = int(args[0])
            return "OK", [(f"{u} (RFC822 {{{len(self.store[u])}}}".encode(), self.store[u]), b")"]
        raise AssertionError(command)

    def logout(self):
        self.calls.append(("logout",))


class TestFetchNew(unittest.TestCase):
    def _fetch(self, **kw):
        base = dict(
            host="h",
            port=993,
            user="u",
            password="p",
            ssl=True,
            folder="INBOX",
            client_factory=FakeImap,
        )
        base.update(kw)
        return imap.fetch_new(**base)

    def test_fetches_only_uids_above_last_seen(self):
        result = self._fetch(last_uid=4)
        mails, client = result.mails, result.client
        self.assertEqual([m.uid for m in mails], [9, 12])
        self.assertEqual([m.sender_email for m in mails], ["b@y.com", "c@z.com"])
        self.assertEqual([m.message_id for m in mails], ["<PO9@t>", "<PO12@t>"])
        self.assertEqual(result.uidvalidity, 1700000000)
        self.assertEqual(result.max_uid, 12)
        self.assertEqual(result.mailbox_max_uid, 12)
        self.assertEqual(result.skipped, [])
        self.assertEqual(client.calls[0], ("login", "u"))
        self.assertEqual(client.calls[1], ("select", "INBOX", True))
        self.assertEqual(client.calls[-1], ("logout",))

    def test_first_run_takes_everything_and_respects_limit(self):
        result = self._fetch(last_uid=0, limit=2)
        self.assertEqual([m.uid for m in result.mails], [4, 9])
        self.assertEqual(result.max_uid, 9)  # only what was consumed; the rest comes next run

    def test_oversize_mail_is_skipped_without_download(self):
        result = self._fetch(last_uid=0, max_bytes=60)
        self.assertEqual(result.mails, [])  # every fake mail is > 60 bytes
        self.assertEqual([u for u, _size in result.skipped], [4, 9, 12])
        self.assertEqual(result.max_uid, 12)  # skipped mails are still passed
        downloads = [
            c
            for c in result.client.calls
            if c[0] == "uid" and c[1] == "FETCH" and c[2][1] == "(RFC822)"
        ]
        self.assertEqual(downloads, [])

    def test_bad_folder_raises_a_clear_error(self):
        with self.assertRaises(imap.ImapError) as ctx:
            self._fetch(last_uid=0, folder="Nope")
        self.assertIn("Nope", str(ctx.exception))

    def test_limit_zero_only_reports_the_mailbox_state(self):
        result = self._fetch(last_uid=0, limit=0)
        self.assertEqual(result.mails, [])
        self.assertEqual(result.max_uid, 0)
        self.assertEqual(result.mailbox_max_uid, 12)
