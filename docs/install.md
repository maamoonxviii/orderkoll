# Install

## Modules on an existing Odoo 19 (on-premise or Odoo.sh)

The quickest path is the Docker install in the [README](../README.md); this section is
for an Odoo 19 you already run.

Python dependencies (light on purpose; no Docling, no PyTorch):

```
pip install pdfplumber pypdf openpyxl            # Orderkoll
pip install "pydantic>=2" instructor litellm      # Orderkoll Pro
# on the official odoo:19 image also: pip install "pyOpenSSL>=24.2"
# optional, for scanned PDFs: apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-swe tesseract-ocr-deu && pip install pytesseract
```

1. Put `orderkoll_core` (this repository) and, if licensed, `orderkoll_pro` in your addons path.
2. Update the apps list and install **Orderkoll** (and **Orderkoll Pro**).
3. Settings → Orderkoll: provider, model, API key (stored as a system parameter), tolerance,
   fuzzy threshold, duplicate window, ignored domains, approval channel.
4. Create an inbox (Orderkoll → Inboxes). Two ways to feed it, usable together:
   - **IMAP**: point the inbox's IMAP settings at the mailbox that receives purchase orders.
   - **Mail alias**: give the inbox an alias (e.g. `po`) on one of your alias domains
     (Settings → Technical → Alias Domains). Mail reaching that address through Odoo's
     incoming-mail gateway (an Incoming Mail Server, or Odoo.sh's catch-all) becomes a
     document of this inbox. Replies on a document's thread stay in its chatter.
   The cron processes new documents every 2 minutes; mail that arrives through the alias
   or IMAP starts processing at once.
5. Optional, Settings → Orderkoll → Monitoring: a Telegram bot token and chat id (and/or an
   alert webhook URL) for a message when a document fails, and a heartbeat URL
   (Healthchecks, Uptime Kuma push) pinged after every processing run. A failed document
   always gets a "Processing failed" task for the inbox's responsible person.
6. On the inbox: **Price source** (pricelist or PO price on the quotation) and **Create
   automatically when clean**. Quotations are always drafts; nothing is confirmed.

### Receiving mail for the alias on-premise

Odoo.sh delivers alias mail by itself. On your own server, mail for the alias domain must
reach Odoo's mail gateway, e.g. with Postfix: an MX record for the alias domain pointing at
the server, port 25 open, and a transport that pipes that one domain into
`odoo-mailgate.py` (shipped with Odoo). Or create an Incoming Mail Server in Odoo that reads
a dedicated mailbox and routes it to the alias.

Optional: `orderkoll_tier_glue` (AGPL-3) if you already run OCA `sale_tier_validation`: on
Odoo 18.0 only for now, until OCA releases `sale_tier_validation` for 19.0.

Installing Orderkoll turns on Odoo's **Pricelists** feature (Sales → Settings): from Odoo 19
a customer's pricelist is ignored while it is off, and Orderkoll checks every price against
it. If someone turns it off later, Orderkoll stops each order with "pricelist: not checked"
instead of comparing against the plain sales price.

## Running the tests

The modules' tests are standard Odoo tests:

```
odoo -d <test database> -i orderkoll_core --test-enable --stop-after-init
```

The service tests (text extraction, matching, IMAP parsing, alerts) also run without Odoo:
`python3 -m unittest discover -s orderkoll_core/tests -t orderkoll_core/tests -p "test_*_service.py"`.
