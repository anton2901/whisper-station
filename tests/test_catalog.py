"""Тесты каталога моделей: имена, размеры, рекомендации, детект устройства."""

from __future__ import annotations

import unittest
from unittest import mock

from whisper_station import catalog


class CatalogTest(unittest.TestCase):
    def test_names_unique_and_ordered(self) -> None:
        names = catalog.names()
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[0], "tiny")
        self.assertIn("large-v3-turbo", names)

    def test_sizes_grow_with_quality(self) -> None:
        sizes = [info.size_mb for info in catalog.CATALOG]
        self.assertEqual(sizes, sorted(sizes))
        self.assertTrue(all(size > 0 for size in sizes))

    def test_every_model_has_repo(self) -> None:
        for info in catalog.CATALOG:
            self.assertIn("/", info.repo)
            self.assertTrue(info.describe().startswith(info.name))

    def test_size_label(self) -> None:
        self.assertEqual(catalog.get("tiny").size_label, "75 МБ")
        self.assertEqual(catalog.get("large-v3-turbo").size_label, "1.6 ГБ")

    def test_default_by_device(self) -> None:
        self.assertEqual(catalog.default_name("cpu"), catalog.CPU_MODEL)
        self.assertEqual(catalog.default_name("cuda"), catalog.GPU_MODEL)
        self.assertEqual(catalog.default_name("auto"), catalog.DEFAULT_MODEL)

    def test_get_unknown(self) -> None:
        self.assertIsNone(catalog.get("nope"))
        self.assertIsNone(catalog.get(""))

    def test_detect_device_cpu_without_driver(self) -> None:
        with mock.patch.object(catalog.subprocess, "run", side_effect=OSError):
            self.assertEqual(catalog.detect_device(), "cpu")

    def test_detect_device_cuda_by_smi(self) -> None:
        probe = mock.Mock(returncode=0, stdout=b"GPU 0: NVIDIA GeForce RTX 4070\n")
        with mock.patch.object(catalog.subprocess, "run", return_value=probe):
            self.assertEqual(catalog.detect_device(), "cuda")


if __name__ == "__main__":
    unittest.main()
