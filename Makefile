PYTHON ?= python3
SRC := .

.PHONY: help run daemon test lint doctor package clean

help:
	@echo "make run      — запустить демон из репозитория"
	@echo "make daemon   — то же через bin/whisper-dictate"
	@echo "make test     — юнит-тесты (unittest)"
	@echo "make lint     — мини-линтер без внешних зависимостей"
	@echo "make doctor   — проверить окружение (хоткей, вставка, сервер)"
	@echo "make package  — собрать пакет через PKGBUILD"

run:
	PYTHONPATH=$(SRC) $(PYTHON) -m whisper_dictate

daemon:
	bin/whisper-dictate daemon

test:
	PYTHONPATH=$(SRC) $(PYTHON) -m unittest discover -s tests -t . -v

lint:
	$(PYTHON) tools/check.py

doctor:
	bin/whisper-dictate doctor

package:
	makepkg -f --nocheck

clean:
	rm -rf build pkg *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
