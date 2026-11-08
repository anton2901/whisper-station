#!/usr/bin/env python3
"""Мини-линтер без внешних зависимостей.

Проверяет: синтаксис, длину строк, табуляцию, хвостовые пробелы,
неиспользуемые импорты, наличие docstring в модулях и print() в коде.
Ruff в проекте не используется намеренно: пакеты ставятся только с согласия.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_LINE = 110
PRINT_ALLOWED = {"app.py", "cli.py"}


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    relative = path.relative_to(ROOT)
    text = path.read_text(encoding="utf-8")

    if "\t" in text:
        errors.append(f"{relative}: табуляция в отступах")
    for number, line in enumerate(text.splitlines(), start=1):
        if len(line) > MAX_LINE:
            errors.append(f"{relative}:{number}: строка {len(line)} симв. > {MAX_LINE}")
        if line != line.rstrip():
            errors.append(f"{relative}:{number}: пробелы в конце строки")

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        errors.append(f"{relative}:{exc.lineno}: синтаксис: {exc.msg}")
        return errors

    is_package_init = path.name == "__init__.py"
    if not is_package_init and relative.parts[0] == "whisper_station" and not ast.get_docstring(tree):
        errors.append(f"{relative}: нет docstring модуля")

    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported[alias.asname or alias.name.split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                imported[alias.asname or alias.name] = node.lineno

    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    if not is_package_init:
        for name, lineno in sorted(imported.items(), key=lambda item: item[1]):
            if name == "annotations":
                continue
            if name not in used:
                errors.append(f"{relative}:{lineno}: импорт {name!r} не используется")

    if relative.parts[0] == "whisper_station" and path.name not in PRINT_ALLOWED:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                errors.append(f"{relative}:{node.lineno}: print() в коде вместо логгера")

    return errors


def main() -> int:
    targets = sorted(
        [*ROOT.glob("whisper_station/**/*.py"), *ROOT.glob("tests/**/*.py"), *ROOT.glob("tools/*.py")]
    )
    errors: list[str] = []
    for path in targets:
        errors.extend(check_file(path))
    if errors:
        print("\n".join(errors))
        print(f"\nлинт: {len(errors)} замечание(й) в {len(targets)} файлах")
        return 1
    print(f"линт: чисто ({len(targets)} файлов)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
