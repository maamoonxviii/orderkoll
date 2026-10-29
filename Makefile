# Orderkoll — repository targets: synthetic test corpus, demo data, accuracy score, lint.
PY ?= python3
CORPUS ?= tools/corpus

.PHONY: corpus seed score lint tools-test

corpus:        ## generate the synthetic PO corpus + ground truth into tools/corpus/
	$(PY) tools/gen_corpus.py --out $(CORPUS)

seed:          ## load the catalogue into a running Odoo (ODOO_URL/ODOO_DB/ODOO_PASSWORD)
	$(PY) tools/seed_demo.py

score:         ## run the corpus through the pipeline and print accuracy per layout
	$(PY) tools/score.py --corpus $(CORPUS)

lint:          ## pre-commit on all files
	pre-commit run --all-files

tools-test:    ## corpus invariants + the modules' pure-Python service tests (no Odoo needed)
	$(PY) -m pytest tools/tests -q
	$(PY) -m unittest discover -s orderkoll_core/tests -t orderkoll_core/tests -p 'test_*service.py'
