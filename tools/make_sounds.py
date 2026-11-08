#!/usr/bin/env python3
"""Генерация звуков старта и остановки записи.

Звуки мягкие и низкие: пара расстроенных синусов с плавным глиссандо,
тихая «воздушная» составляющая через однополюсный фильтр и длинный спад.
Никаких резких атак и высоких обертонов — чтобы не резало слух.

Запуск: python3 tools/make_sounds.py  (кладёт WAV в packaging/sounds/)
"""

from __future__ import annotations

import array
import math
import random
import wave
from pathlib import Path

RATE = 48000
OUT_DIR = Path(__file__).resolve().parent.parent / "packaging" / "sounds"


def _envelope(t: float, duration: float, attack: float, tau: float) -> float:
    """Плавная атака + экспоненциальный спад + мягкий хвост."""
    if t < attack:
        shape = math.sin(math.pi / 2 * (t / attack))
    else:
        shape = math.exp(-(t - attack) / tau)
    tail = min(1.0, max(0.0, (duration - t) / 0.025))
    return shape * tail


def _sweep(t: float, f0: float, f1: float, duration: float) -> float:
    """Частота с плавным глиссандо и лёгким «дыханием»."""
    progress = t / duration
    return f0 * (f1 / f0) ** progress


def _lowpassed_noise(rng: random.Random, count: int, cutoff_hz: float) -> list[float]:
    alpha = min(1.0, 2 * math.pi * cutoff_hz / RATE)
    value = 0.0
    result = []
    for _ in range(count):
        value += alpha * (rng.uniform(-1.0, 1.0) - value)
        result.append(value)
    return result


def make_tone(
    *,
    duration: float,
    partials: tuple[tuple[float, float, float], ...],
    attack: float,
    tau: float,
    noise_level: float,
    noise_cutoff: float,
    peak: float,
    seed: int,
) -> bytes:
    """Собрать моно PCM16.

    partials: (частота в начале, частота в конце, амплитуда).
    """
    count = int(RATE * duration)
    rng = random.Random(seed)
    noise = _lowpassed_noise(rng, count, noise_cutoff)
    samples = array.array("h", bytes(2 * count))
    raw = [0.0] * count
    phases = [0.0] * len(partials)
    for index in range(count):
        t = index / RATE
        env = _envelope(t, duration, attack, tau)
        value = 0.0
        for part, (f0, f1, amp) in enumerate(partials):
            phases[part] += 2 * math.pi * _sweep(t, f0, f1, duration) / RATE
            value += amp * math.sin(phases[part])
        value += noise_level * noise[index]
        raw[index] = value * env
    top = max((abs(value) for value in raw), default=0.0) or 1.0
    scale = peak * 32767 / top
    for index, value in enumerate(raw):
        samples[index] = int(max(-32767, min(32767, value * scale)))
    return samples.tobytes()


def write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm)


def main() -> int:
    start = make_tone(
        duration=0.34,
        # Расстроенная пара создаёт медленные «космические» биения.
        partials=((196.0, 262.0, 1.0), (197.6, 263.6, 0.8), (98.0, 131.0, 0.35)),
        attack=0.05,
        tau=0.13,
        noise_level=0.05,
        noise_cutoff=900.0,
        peak=0.20,
        seed=7,
    )
    stop = make_tone(
        duration=0.42,
        partials=((262.0, 174.0, 1.0), (263.4, 175.0, 0.8), (131.0, 87.0, 0.4)),
        attack=0.035,
        tau=0.19,
        noise_level=0.04,
        noise_cutoff=700.0,
        peak=0.16,
        seed=11,
    )
    write_wav(OUT_DIR / "start.wav", start)
    write_wav(OUT_DIR / "stop.wav", stop)
    print(f"готово: {OUT_DIR}/start.wav, stop.wav")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
