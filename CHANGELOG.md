# Changelog

All user-visible changes, newest first. Odoo-style tags: ADD, IMP, FIX, REM.

## 18.0.1.0.1 (2026-10-29)

- [FIX] orderkoll_core: a spreadsheet that unzips to more than 50 MB, or to over 100 times its own
  size (a "zip bomb"), is refused before it is opened, instead of filling the server's memory.
- [IMP] orderkoll_core: the store page and cover say Community (Enterprise is listed again once it
  has been tested on Enterprise).
- [FIX] orderkoll_core, orderkoll_tier_glue: each module folder carries its own licence text
  (LGPL-3, AGPL-3), so the Odoo App Store shows the right licence for each module.
- [FIX] orderkoll_core: when a document that failed (for example, the AI provider's limit was
  reached) is processed successfully later, its "Processing failed" to-do is closed with a note.
- [IMP] orderkoll_core: Settings → API base URL, for an OpenAI-compatible endpoint (Azure, Ollama, vLLM, Cloudflare Workers AI). The approval channel reads "n8n webhook (Slack)"; Teams is not built yet.
- [ADD] orderkoll_tier_glue (AGPL-3, optional): with the inbox switch on, a document that
  passes every check becomes a draft quotation with OCA tier validation requested on it.
- [FIX] n8n: the Slack click workflow answers Slack first and keeps the raw request, so
  Slack's signature can be checked (n8n drops the raw body when no response body is set).
- [ADD] n8n: Slack approval workflows (request with Approve / Reject buttons; signed click
  back to Odoo; message updated with the result) and their setup guide.
- [IMP] settings: no default LLM provider or model; nothing is sent to any provider until
  you choose the model and enter its key.
- [FIX] docs: Docker install fixed after a clean-machine test (pip vs. Ubuntu packages),
  explicit steps for Pro and for trying a sample; `tools/send_eml.py` feeds a saved email
  into Odoo (Odoo 18's own mail-gateway script is Python 2).
- [IMP] docs: README with a 10-minute Docker install on Odoo 18, first steps and a
  synthetic sample email to try it without a mail server; module README updated.
- [ADD] orderkoll_core: Create quotation. A ready document becomes a draft quotation
  (never confirmed): customer, PO number as customer reference, requested date, the
  checked lines with prices from the pricelist or the PO (inbox setting), the PO file
  attached and the checks log in its chatter; quotation and document link to each other.
  "Create automatically when clean" does it without a click after processing.
- [ADD] orderkoll_core: failures create a "Processing failed" task for the inbox's
  responsible person and, if configured, a Telegram message and/or a webhook alert
  (no document content in the alert). Heartbeat URL pinged after every processing run.
  New mail starts processing at once instead of at the next 2-minute run. Hook
  `_orderkoll_on_ready()` runs each time a document becomes ready.
- [ADD] orderkoll_core: review screen. The purchase order is shown beside its lines with
  coloured status chips and a plain-language "To do" box; Map (product picker that can
  remember the code for the customer), Pick/Change customer, Mark scan as checked,
  Re-check, and Reject with a required reason. Any edit to a line or to the PO header
  re-runs the checks and posts one summary to the chatter. The document list opens on
  "To do" (needs review, ready, errors).
- [ADD] orderkoll_core: mail alias intake. An inbox can have an alias (e.g. `po@your-odoo-domain`);
  mail delivered through Odoo's incoming-mail gateway becomes a document exactly like IMAP
  mail (same dedup, same sanitised attachments). Duplicate Message-IDs are refused, the alias
  owner always wins over edited alias defaults, and review activities are never assigned to
  the system user.
- [ADD] orderkoll_core: customer resolution (email → domain, never webmail) with the Pick
  customer wizard; product matching chain (code memory → reference → barcode → name, sizes
  strict) with Remember mapping; optional OCR for scanned PDFs (Tesseract) — OCR-read
  documents always go to review.
- [ADD] orderkoll_core: inbox with IMAP intake (read-only, UID-tracked, starts at the newest
  mail when enabled), one document per mail with the original attachment and extracted text
  (pdfplumber → pypdf, openpyxl, CSV, cleaned email bodies), customer code memory, settings,
  user/manager groups, per-company rules, two crons.
- [FIX] intake: one malformed or oversized mail no longer blocks the mailbox; UIDVALIDITY
  changes are detected; mail dates stored in UTC; forwarded POs keep their content; a
  transient engine failure is retried three times before the document errors.
- [ADD] tools: synthetic PO corpus generator (`gen_corpus.py`: 30 text PDFs in 10 layouts,
  5 XLSX, 5 EML, 5 scanned-style PDFs, ground truth per document) and demo seeder
  (`seed_demo.py`: 8 partners with pricelists, 200 products with codes and barcodes).
