# Orderkoll

Orderkoll turns purchase orders that customers send by email (PDF, Excel/CSV, or the
email text) into **draft** Odoo quotations. It finds the customer, matches every line to
your products, checks each price against that customer's pricelist and the lines against
the printed total, flags repeated PO numbers, and stops anything doubtful for a person.
Nothing is confirmed automatically.

Status: **beta** (October 2026), Odoo 20.0 Community (this branch; Odoo 18.0 and 19.0 on
their own branches). On the
[Odoo App Store](https://apps.odoo.com/apps/modules/20.0/orderkoll_core).

| Directory | What | Licence |
|---|---|---|
| `orderkoll_core/` | the free module: inbox (mail alias or IMAP), documents, text extraction, customer and product matching, review screen, quotation creation, alerts | LGPL-3 |
| `orderkoll_tier_glue/` | optional: checked orders become quotations that wait for OCA tier validation (Odoo 18.0 and 19.0 only for now: OCA's `sale_tier_validation` has no 20.0 release yet) | AGPL-3 |
| `n8n/` | Slack / Teams approval workflow templates | MIT |
| `tools/` | synthetic test-PO generator, demo data, accuracy scorer | MIT |
| `docs/` | install details, [review guide for the order desk](docs/review-guide.md) | — |

**Orderkoll Pro** (paid, separate module `orderkoll_pro`) adds the AI extraction of the
order lines with your own LLM key, and the price, totals and duplicate checks. Without
it, Orderkoll stores every purchase order and its text, and a person enters the lines.

## Install on Odoo 20 with Docker (about 10 minutes)

You need Docker (with the compose plugin), Git and Python 3. The slowest part is the
first download of the Odoo and PostgreSQL images (about 1 GB). Run every command from the
same terminal, in the folder created in step 1.

**1. Get Orderkoll.**

```bash
mkdir orderkoll-odoo && cd orderkoll-odoo
git clone --branch 20.0 https://github.com/maamoonxviii/orderkoll.git addons
```

If you bought **Orderkoll Pro**, copy its `orderkoll_pro` folder into `addons/` now, next
to `orderkoll_core`.

**2. Describe the image and the services.** Paste both blocks as they are. Without
Orderkoll Pro you may afterwards delete the last `RUN` line (and the line above it) from
`Dockerfile`: it only adds the AI libraries Pro needs.

```bash
cat > Dockerfile <<'DOCKERFILE'
FROM odoo:20
USER root
# Orderkoll. --ignore-installed: newer copies of a few libraries the image ships from Ubuntu.
RUN pip3 install --break-system-packages --ignore-installed --no-cache-dir \
    pdfplumber pypdf openpyxl "pyOpenSSL>=24.2"
# Scanned PDFs (optional; delete these two lines if your customers never send scans):
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* && pip3 install --break-system-packages --no-cache-dir pytesseract
# Orderkoll Pro only:
RUN pip3 install --break-system-packages --ignore-installed --no-cache-dir \
    "pydantic>=2" instructor litellm
USER odoo
DOCKERFILE

cat > docker-compose.yml <<'COMPOSE'
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: odoo
      POSTGRES_PASSWORD: odoo
      POSTGRES_DB: postgres
    volumes: [db:/var/lib/postgresql/data]
  odoo:
    build: .
    depends_on: [db]
    ports: ["127.0.0.1:8069:8069"]
    environment:
      HOST: db
      USER: odoo
      PASSWORD: odoo
    volumes:
      - ./addons:/mnt/extra-addons
      - odoo:/var/lib/odoo
volumes: {db: {}, odoo: {}}
COMPOSE
```

**3. Build, create the database, start.**

```bash
docker compose build
```

Then **one** of these two, depending on what you have:

```bash
# Orderkoll only
docker compose run --rm odoo odoo -d orderkoll -i orderkoll_core --without-demo=all --stop-after-init
```

```bash
# Orderkoll and Orderkoll Pro
docker compose run --rm odoo odoo -d orderkoll -i orderkoll_core,orderkoll_pro --without-demo=all --stop-after-init
```

And start it:

```bash
docker compose up -d
```

Open http://localhost:8069 and log in with **admin / admin**. Change that password under
Settings → Users. The **Orderkoll** app is in the main menu.

**Already running Odoo 20** on your own server? Add the `orderkoll_core` folder (and
`orderkoll_pro`) to your addons path, `pip install pdfplumber pypdf openpyxl` (for Pro also
`pydantic instructor litellm`), update the Apps list and install **Orderkoll**. Details in
[docs/install.md](docs/install.md).

## First steps

1. **An inbox.** Orderkoll → Configuration → Inboxes → New. Give it a mail alias such as
   `po` on one of your alias domains, or the IMAP login of a mailbox that only receives
   purchase orders. Pick a *Responsible* person: they get the tasks.
2. **Settings** (Orderkoll → Configuration → Settings): with Pro, your LLM provider, model
   and API key; the price tolerance, ignored webmail domains, and optional Telegram /
   webhook alerts and a heartbeat URL.
3. **Customers and products** come from Odoo itself: the sender's email or domain finds
   the customer, and product codes, barcodes or names find the products.

### Try it without a mail server

After the Docker install, in the same folder:

1. In Odoo, open Settings → General Settings and find **Alias Domain**. Type `orders.test`
   in the field, click *Create "orders.test"* in the list that opens, then click *Save*.
2. Orderkoll → Configuration → Inboxes → New: name *Purchase orders*, alias `po` (the
   domain shows `orders.test`), Responsible *Administrator*. Save.
3. Send the sample purchase order. The script asks for the password you log in to Odoo
   with (`admin` on a fresh install); in a script, set `ODOO_PASSWORD` instead.

   ```bash
   python3 addons/tools/send_eml.py --db orderkoll --login admin addons/docs/samples/sample-po.eml
   ```

Orderkoll → Documents now shows it. A fresh database has no customers, so it waits in
**Needs review**, and its To-do box says "Pick the customer". Reading the order lines and
the PO number is Orderkoll Pro's AI step: without Pro, or with Pro but no LLM key in
Orderkoll → Configuration → Settings yet, the box also says the lines were not read. The [review guide](docs/review-guide.md) explains every button.

## Development

How to run the tests is in [docs/install.md](docs/install.md). Tools only, no Odoo needed:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r tools/requirements.txt
make corpus       # 45 synthetic purchase orders + answer key into tools/corpus/
make tools-test
```

Synthetic data only: no real company, person, product or price appears in this repository.
