# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Import the pure-Python services both under Odoo's test runner and under plain
pytest (fast local TDD without an Odoo instance)."""

import importlib.util
import pathlib
import sys

try:  # inside Odoo: odoo.addons.orderkoll_core.tests
    from ..services import extract, imap, match  # noqa: F401
except ImportError:  # plain pytest from the repository root
    _services = pathlib.Path(__file__).resolve().parents[1] / "services"

    def _load(name):
        spec = importlib.util.spec_from_file_location(
            f"orderkoll_services_{name}", _services / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    extract = _load("extract")
    imap = _load("imap")
    match = _load("match")

DATA = pathlib.Path(__file__).resolve().parent / "data"
