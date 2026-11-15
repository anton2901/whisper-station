PYTHON ?= python3
SRC := .
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)

.PHONY: help run daemon test lint doctor package clean release

help:
	@echo "make run      — запустить демон из репозитория"
	@echo "make daemon   — то же через bin/whisper-station"
	@echo "make test     — юнит-тесты (unittest)"
	@echo "make lint     — мини-линтер без внешних зависимостей"
	@echo "make doctor   — проверить окружение (хоткей, вставка, сервер)"
	@echo "make package  — собрать пакет через PKGBUILD"
	@echo "make release  — проверить, поставить тег v$(VERSION) и запустить релиз на GitHub"

run:
	PYTHONPATH=$(SRC) $(PYTHON) -m whisper_station daemon

daemon:
	bin/whisper-station daemon

test:
	PYTHONPATH=$(SRC) $(PYTHON) -m unittest discover -s tests -t . -v

lint:
	$(PYTHON) tools/check.py

doctor:
	bin/whisper-station doctor

package:
	makepkg -f --nocheck

# Черновик релиза собирает GitHub Actions (.github/workflows/release.yml):
# остаётся нажать Publish.
release:
	@test -z "$$(git status --porcelain)" || { echo "Сначала закоммитьте изменения"; exit 1; }
	@git rev-parse -q --verify "refs/tags/v$(VERSION)" >/dev/null && { \
		echo "Тег v$(VERSION) уже есть: поднимите версию в pyproject.toml/PKGBUILD"; exit 1; }
	$(MAKE) lint test
	git tag -a "v$(VERSION)" -m "whisper-station $(VERSION)"
	git push origin "v$(VERSION)"
	@echo "Тег v$(VERSION) отправлен: черновик релиза появится в Actions, останется нажать Publish"

clean:
	rm -rf build pkg *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
