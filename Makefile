PYTHON ?= python
.PHONY: install test lint up down ingest run eval bench-cache bench-acl bench-graph dashboard report
install test lint up down ingest run eval bench-cache bench-acl bench-graph dashboard report:
	$(PYTHON) tasks.py $@
