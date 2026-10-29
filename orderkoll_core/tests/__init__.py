import importlib.util

if importlib.util.find_spec("odoo"):  # plain unittest outside Odoo runs the service tests only
    from . import (
        test_alerts_service,
        test_alias,
        test_document,
        test_extract_service,
        test_imap_service,
        test_match_service,
        test_matching,
        test_partner,
        test_quotation,
        test_review,
    )
