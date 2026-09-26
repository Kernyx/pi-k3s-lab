.PHONY: prepare up check smoke test lint

prepare up check smoke:
	SSH_HOST="$(SSH_HOST)" bash scripts/remote.sh $@

test:
	python3 -m unittest discover -s tests -v

lint:
	for script in scripts/*.sh; do bash -n "$$script"; done
	shellcheck -x scripts/*.sh
