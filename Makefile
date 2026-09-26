.PHONY: prepare up check smoke deploy app-check configure open test lint

prepare up check smoke deploy app-check configure open:
	SSH_HOST="$(SSH_HOST)" LINKS_FILE="$(LINKS_FILE)" bash scripts/remote.sh $@

test:
	python3 -m unittest discover -s tests -v

lint:
	for script in scripts/*.sh; do bash -n "$$script"; done
	shellcheck -x scripts/*.sh
