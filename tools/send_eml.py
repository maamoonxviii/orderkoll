#!/usr/bin/env python3
# Copyright 2026 Maamoon Mara
# License MIT (https://opensource.org/licenses/MIT).
"""Feed a saved email (.eml) into Odoo's mail gateway, as if it had arrived by mail.

Odoo routes it like real incoming mail: to the inbox whose alias is in the To: address.
Handy for trying Orderkoll without a mail server. Python 3 standard library only.

    python3 tools/send_eml.py --db orderkoll --login admin docs/samples/sample-po.eml

The password is read from the ODOO_PASSWORD environment variable, else asked for.
"""

import argparse
import getpass
import os
import sys
import xmlrpc.client


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        epilog="Password: the ODOO_PASSWORD environment variable, else you are asked.",
    )
    parser.add_argument("eml", help="path to the .eml file ('-' reads standard input)")
    parser.add_argument("--url", default="http://127.0.0.1:8069", help="Odoo address")
    parser.add_argument("--db", required=True, help="database name")
    parser.add_argument("--login", default="admin", help="Odoo user (default: admin)")
    args = parser.parse_args(argv)

    password = os.environ.get("ODOO_PASSWORD") or getpass.getpass(f"Password for {args.login}: ")
    raw = sys.stdin.buffer.read() if args.eml == "-" else open(args.eml, "rb").read()

    common = xmlrpc.client.ServerProxy(f"{args.url}/xmlrpc/2/common")
    uid = common.authenticate(args.db, args.login, password, {})
    if not uid:
        sys.exit("Login failed: check --db, --login and the password.")
    models = xmlrpc.client.ServerProxy(f"{args.url}/xmlrpc/2/object", allow_none=True)
    record_id = models.execute_kw(
        args.db,
        uid,
        password,
        "mail.thread",
        "message_process",
        [False, xmlrpc.client.Binary(raw)],
        {},
    )
    print(f"Delivered: Odoo created or updated record {record_id}.")


if __name__ == "__main__":
    main()
