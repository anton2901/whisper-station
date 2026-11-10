"""Пост-коррекция распознанного текста: словарь терминов, филлеры, повторы.

Сервер Whisper игнорирует `prompt`/`hotwords`, поэтому имена и термины правим
уже готовый текст. Модуль чистый: без Qt, без сети и без файлов — только строки.

Порядок обработки: словарь → филлеры → повторы → пробелы → хвостовой пробел.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

from .config import Config

log = logging.getLogger(__name__)

# Универсальные филлеры: «не-слова», которые не зависят от языка. Сравнение идёт
# по форме с удалёнными повторами букв, поэтому «эээ» и «ммм» тоже ловятся.
UNIVERSAL_FILLERS = frozenset({"э", "эм", "м", "хм", "uh", "uhm", "hm"})
# Языковые филлеры: убираем только при явном свидетельстве английского языка.
EN_FILLERS = frozenset({"um", "ah", "eh"})

MAX_NGRAM = 3
_REPEATS = re.compile(r"(.)\1+")
_SPACES = re.compile(r"\s+")
_SPACE_BEFORE = re.compile(r"\s+([,.;:!?…\)\]\}])")
_SPACE_AFTER_OPEN = re.compile(r"([\(\[\{])\s+")


@dataclass(frozen=True)
class _Token:
    """Слово с пунктуацией по краям; ядро — только буквы и цифры."""

    prefix: str
    core: str
    suffix: str


def _split_token(token: str) -> _Token | None:
    """Отделить пунктуацию от ядра; None — токен без букв и цифр."""
    start = next((index for index, char in enumerate(token) if char.isalnum()), None)
    if start is None:
        return None
    end = next(
        index for index in range(len(token) - 1, -1, -1) if token[index].isalnum()
    )
    return _Token(token[:start], token[start : end + 1], token[end + 1 :])


def _normalize(text: str) -> str:
    """Ключ для сравнения: только буквы и цифры, без регистра."""
    return "".join(char.casefold() for char in text if char.isalnum())


def _levenshtein(left: str, right: str, limit: int) -> int:
    """Расстояние редактирования, но не больше `limit`; дальше — ранний выход.

    Считаем только полосу шириной `limit` вокруг диагонали: путь с большим
    числом правок всё равно не пройдёт порог словаря.
    """
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    if len(left) < len(right):
        left, right = right, left
    inf = limit + 1
    previous = [column if column <= limit else inf for column in range(len(right) + 1)]
    for row, left_char in enumerate(left, start=1):
        current = [inf] * (len(right) + 1)
        current[0] = row if row <= limit else inf
        row_min = current[0]
        start = max(1, row - limit)
        end = min(len(right), row + limit)
        for column in range(start, end + 1):
            current[column] = min(
                previous[column - 1] + (left_char != right[column - 1]),
                previous[column] + 1,
                current[column - 1] + 1,
            )
            if current[column] < row_min:
                row_min = current[column]
        if row_min > limit:
            return inf
        previous = current
    return previous[-1]


def _dictionary_entries(words: Iterable[str]) -> list[tuple[str, str]]:
    """Пары (ключ для сравнения, как писать). Дубликаты по ключу отбрасываем."""
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for word in words:
        written = word.strip()
        key = _normalize(written)
        if not key or key in seen:
            continue
        seen.add(key)
        entries.append((key, written))
    return entries


def _score(key: str, target: str, threshold: float) -> float | None:
    """Нормированное расхождение; None — совпадение заведомо невозможно."""
    if key == target:
        return 0.0
    # Как в Handy: разница длин до 25 % (минимум 2 символа), иначе это другое слово.
    if abs(len(key) - len(target)) > max(2, int(len(target) * 0.25)):
        return None
    longest = max(len(key), len(target))
    limit = int(threshold * longest)
    distance = _levenshtein(key, target, limit)
    return distance / longest if distance <= limit else None


def _match_case(written: str, original: str) -> str:
    """Сохранить регистр распознанного слова, а не словаря."""
    letters = [char for char in original if char.isalpha()]
    if len(letters) > 1 and all(char.isupper() for char in letters):
        return written.upper()
    if letters and letters[0].isupper() and written[:1].islower():
        return written[:1].upper() + written[1:]
    return written


def _length_window(length: int) -> range:
    """Длины словарных слов, которые ещё могут пройти проверку 25 %."""
    low = max(1, int(length / 1.3))
    return range(low, int(length * 1.3) + 4)


def apply_custom_words(text: str, words: Iterable[str], threshold: float = 0.18) -> str:
    """Заменить похожие n-граммы (1–3 слова) на термины из словаря.

    Регистр и пунктуация вокруг слова сохраняются; кириллица сравнивается тем же
    расстоянием Левенштейна, без Soundex-эвристик для латиницы.
    """
    entries = _dictionary_entries(words)
    if not entries or not text.strip():
        return text
    exact = dict(entries)
    by_length: dict[int, list[tuple[str, str]]] = {}
    for entry in entries:
        by_length.setdefault(len(entry[0]), []).append(entry)

    raw = text.split()
    parts = [_split_token(token) for token in raw]
    output: list[str] = []
    index = 0
    while index < len(raw):
        best: tuple[float, int, str] | None = None
        for span in range(MAX_NGRAM, 0, -1):
            last = index + span - 1
            if last >= len(raw):
                continue
            window = parts[index : last + 1]
            if any(part is None for part in window):
                continue
            key = "".join(_normalize(part.core) for part in window if part is not None)
            if not key:
                continue
            written = exact.get(key)
            if written is not None:
                # Точное совпадение длиннее любого нечёткого: короче уже не ищем.
                best = (0.0, last, written)
                break
            for target_length in _length_window(len(key)):
                for target, candidate in by_length.get(target_length, ()):
                    score = _score(key, target, threshold)
                    # Строгое «лучше»: при равном счёте выигрывает более длинное окно.
                    if score is not None and (best is None or score < best[0]):
                        best = (score, last, candidate)
            if best is not None and best[0] == 0.0:
                break
        if best is None:
            output.append(raw[index])
            index += 1
            continue
        _, last, written = best
        first_part = parts[index]
        last_part = parts[last]
        assert first_part is not None and last_part is not None
        matched = _match_case(written, first_part.core)
        output.append(first_part.prefix + matched + last_part.suffix)
        index = last + 1
    return " ".join(output)


def _looks_english(text: str) -> bool:
    """Грубое свидетельство языка: буквы есть и все они латинские."""
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and all(char.isascii() for char in letters)


def _filler_base(core: str) -> str:
    """«Ээээ» → «э», «хммм» → «хм»: сводим растянутые филлеры к базовой форме."""
    return _REPEATS.sub(r"\1", core.casefold())


def _sentence_start(kept: list[str]) -> bool:
    if not kept:
        return True
    tail = kept[-1].rstrip("\"'»)]}")
    return bool(tail) and tail[-1] in ".!?…"


def remove_filler_words(
    text: str,
    language: str = "ru",
    fillers: Iterable[str] | None = None,
) -> str:
    """Убрать слова-филлеры; список пользователя заменяет встроенный.

    Языковые филлеры (um/ah/eh) удаляются только для английского текста: при
    `auto` считаем английским текст, где все буквы латинские.
    """
    tokens = text.split()
    if not tokens:
        return text
    custom = [word for word in (fillers or ()) if _normalize(word)]
    if custom:
        allowed = {_filler_base(_normalize(word)) for word in custom}
    else:
        allowed = set(UNIVERSAL_FILLERS)
        if language == "en" or (language == "auto" and _looks_english(text)):
            allowed |= EN_FILLERS

    kept: list[str] = []
    capitalize_next = False
    for token in tokens:
        part = _split_token(token)
        if part is None:
            kept.append(token)
            continue
        # Односложные «м»/«э» не считаем филлерами: это может быть буква.
        if len(part.core) >= 2 and _filler_base(part.core) in allowed:
            if part.core[:1].isupper() and _sentence_start(kept):
                capitalize_next = True
            continue
        # Заглавную букву удалённого филлера отдаём ровно следующему слову.
        if capitalize_next:
            kept.append(part.prefix + part.core[:1].upper() + part.core[1:] + part.suffix)
            capitalize_next = False
        else:
            kept.append(token)
    return " ".join(kept)


def collapse_stutters(text: str) -> str:
    """Схлопнуть три и более одинаковых подряд идущих слова в одно."""
    tokens = text.split()
    parts = [_split_token(token) for token in tokens]
    output: list[str] = []
    index = 0
    while index < len(tokens):
        part = parts[index]
        if part is None or not part.core.isalpha():
            output.append(tokens[index])
            index += 1
            continue
        key = part.core.casefold()
        last = index
        while last + 1 < len(tokens):
            following = parts[last + 1]
            if (
                following is None
                or not following.core.isalpha()
                or following.core.casefold() != key
            ):
                break
            last += 1
        if last - index + 1 >= 3:
            last_part = parts[last]
            assert last_part is not None
            output.append(part.prefix + part.core + last_part.suffix)
            index = last + 1
        else:
            output.append(tokens[index])
            index += 1
    return " ".join(output)


def normalize_text(text: str) -> str:
    """Схлопнуть пробелы и убрать лишние пробелы вокруг знаков препинания."""
    text = _SPACES.sub(" ", text).strip()
    text = _SPACE_BEFORE.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN.sub(r"\1", text)
    return text


def describe_rules(cfg: Config) -> str:
    """Короткая строка для `doctor`: какие правила текста включены."""
    parts: list[str] = []
    if cfg.dictionary_words:
        parts.append(
            f"словарь {len(cfg.dictionary_words)} слов (порог {cfg.dictionary_threshold:.2f})"
        )
    else:
        parts.append("словарь пуст")
    if cfg.remove_fillers:
        parts.append("филлеры")
    if cfg.collapse_stutters:
        parts.append("повторы")
    if cfg.trailing_space:
        parts.append("пробел в конце")
    return ", ".join(parts)


def process_text(text: str, cfg: Config) -> str:
    """Полная цепочка чистки текста перед вставкой."""
    if not text.strip():
        return ""
    result = text
    if cfg.dictionary_words:
        result = apply_custom_words(result, cfg.dictionary_words, cfg.dictionary_threshold)
    if cfg.remove_fillers:
        result = remove_filler_words(result, cfg.language, cfg.fillers)
    if cfg.collapse_stutters:
        result = collapse_stutters(result)
    result = normalize_text(result)
    if cfg.trailing_space and result:
        result += " "
    if result != text:
        log.debug("textproc: %d → %d символов", len(text), len(result))
    return result
