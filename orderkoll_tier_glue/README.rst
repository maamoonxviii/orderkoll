===================
Orderkoll Tier Glue
===================

.. |badge1| image:: https://img.shields.io/badge/maturity-Beta-yellow.png
    :target: https://odoo-community.org/page/development-status
    :alt: Beta
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
    :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
    :alt: License: AGPL-3

|badge1| |badge2|

For teams that already approve quotations with OCA *Sale Tier Validation*: when a
purchase order read by Orderkoll passes every check, the draft quotation is created
at once and tier validation is requested on it. It cannot be confirmed until the
reviewers have validated it.

Optional. It depends only on *Orderkoll* and *Sale Tier Validation*.

**Table of contents**

.. contents::
   :local:

Configuration
=============

#. Settings > Technical > Tier Validation > Tier Definition: a definition for the
   model *Sales Order*, with the reviewers you want. The domain
   ``[('orderkoll_document_id', '!=', False)]`` limits it to quotations created by
   Orderkoll.
#. Orderkoll > Configuration > Inboxes: tick *Quotation + tier validation when ready*.

Usage
=====

A document that passes every check becomes *Quotation created*; its quotation shows
the requested reviews. Reviewers validate or reject it from the quotation.

Credits
=======

Authors
~~~~~~~

* Maamoon Mara

Maintainers
~~~~~~~~~~~

This module is maintained by Maamoon Mara.
