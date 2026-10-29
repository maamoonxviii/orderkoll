=========
Orderkoll
=========

.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
    :target: https://odoo-community.org/page/development-status
    :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-LGPL--3-blue.png
    :target: http://www.gnu.org/licenses/lgpl-3.0-standalone.html
    :alt: License: LGPL-3

|badge1| |badge2|

Orderkoll turns emailed purchase orders (PDF, Excel/CSV, or the email body)
into draft Odoo quotations. This module is the free core:

* intake by mail alias (Odoo's own incoming mail) or by IMAP from a mailbox that
  only receives purchase orders; one document per mail with the original file,
  the sender and the text extracted from it (pdfplumber, pypdf, openpyxl; scanned
  PDFs through optional Tesseract OCR, always routed to a person),
* the customer from the sender (exact email, then domain; never webmail domains)
  and each line's product (customer code memory, internal reference, barcode,
  name similarity),
* the review screen: the purchase order beside its lines, a plain-language To-do
  box, Map product, Pick customer, Reject with a reason; every edit re-runs the
  checks,
* Create quotation: a draft ``sale.order`` with the PO number as customer
  reference, the original file attached and every check in its chatter,
* a task for the responsible person when a document fails, optional Telegram or
  webhook alerts, and a heartbeat URL for your monitor.

Nothing is confirmed automatically. The AI extraction of the order lines and the
price, totals and duplicate checks are in the separate module *Orderkoll Pro*.

**Table of contents**

.. contents::
   :local:

Installation
============

Python dependencies: ``pdfplumber``, ``pypdf``, ``openpyxl`` (and a recent
``pyOpenSSL`` on the official Docker image). Optional for scanned PDFs:
``pytesseract`` with the ``tesseract-ocr`` system package.

Configuration
=============

#. Orderkoll → Configuration → Inboxes: create one. Either give it a mail alias
   (``po`` on one of your alias domains) or the IMAP login of a dedicated
   mailbox. Choose the *Responsible* person, the price source for quotations
   (pricelist or the PO's price) and whether a clean document becomes a
   quotation without a click.
#. Orderkoll → Configuration → Settings: extraction engine (Orderkoll Pro),
   tolerances, ignored sender domains, approval channel, and Monitoring
   (Telegram / webhook alerts, heartbeat URL).
#. Two groups: *Orderkoll / User* (the order desk; includes Sales: own
   documents) works documents; *Orderkoll / Manager* configures inboxes and sees
   the AI audit tab.

Usage
=====

Orderkoll → Documents opens on *To do*. Yellow rows need a person, green rows
are ready. Open one: the yellow box says what is missing, and each fix is one
button. When the box is empty the document turns *Ready*; *Create quotation*
makes the draft. A step-by-step guide for the order desk is in the
repository's ``docs/review-guide.md``.

Known issues / Roadmap
======================

* Slack / Teams approval buttons through n8n (next version).

Bug Tracker
===========

Bugs are tracked on the project's issue tracker.

Credits
=======

Authors
~~~~~~~

* Maamoon Mara

Maintainers
~~~~~~~~~~~

This module is maintained by Maamoon Mara.
