"""Тесты пост-коррекции текста: словарь, филлеры, повторы, порядок обработки."""

from __future__ import annotations

import unittest

from whisper_station import textproc
from whisper_station.config import Config


class CustomWordsTest(unittest.TestCase):
    def test_exact_word_uses_dictionary_case(self) -> None:
        result = textproc.apply_custom_words("запусти kubernetes", ["Kubernetes"])
        self.assertEqual(result, "запусти Kubernetes")

    def test_fuzzy_cyrillic(self) -> None:
        result = textproc.apply_custom_words("кубернетис работает", ["кубернетес"])
        self.assertEqual(result, "кубернетес работает")

    def test_sentence_start_keeps_capital(self) -> None:
        result = textproc.apply_custom_words("Кубернетис работает", ["кубернетес"])
        self.assertEqual(result, "Кубернетес работает")

    def test_all_caps_is_preserved(self) -> None:
        result = textproc.apply_custom_words("КУБЕРНЕТЕС", ["кубернетес"])
        self.assertEqual(result, "КУБЕРНЕТЕС")

    def test_ngram_merges_words(self) -> None:
        result = textproc.apply_custom_words("charge bee today", ["ChargeBee"])
        self.assertEqual(result, "ChargeBee today")

    def test_ngram_keeps_punctuation(self) -> None:
        result = textproc.apply_custom_words("Запусти charge bee, потом", ["ChargeBee"])
        self.assertEqual(result, "Запусти ChargeBee, потом")

    def test_multiword_term_matches_joined_key(self) -> None:
        result = textproc.apply_custom_words("вобщем готово", ["в общем"])
        self.assertEqual(result, "в общем готово")

    def test_unrelated_word_is_not_replaced(self) -> None:
        result = textproc.apply_custom_words("кубик и стол", ["кубернетес"])
        self.assertEqual(result, "кубик и стол")

    def test_short_word_is_not_fuzzy_matched(self) -> None:
        result = textproc.apply_custom_words("тест", ["тесто"])
        self.assertEqual(result, "тест")

    def test_empty_dictionary_returns_text(self) -> None:
        result = textproc.apply_custom_words("привет,  мир", [])
        self.assertEqual(result, "привет,  мир")

    def test_zero_threshold_allows_only_exact(self) -> None:
        result = textproc.apply_custom_words("кубернетис", ["кубернетес"], threshold=0.0)
        self.assertEqual(result, "кубернетис")

    def test_punctuation_around_word_is_kept(self) -> None:
        result = textproc.apply_custom_words("«кубернетис», привет!", ["кубернетес"])
        self.assertEqual(result, "«кубернетес», привет!")


class FillersTest(unittest.TestCase):
    def test_universal_fillers(self) -> None:
        self.assertEqual(textproc.remove_filler_words("ээ привет"), "привет")
        self.assertEqual(textproc.remove_filler_words("ну ммм дальше"), "ну дальше")
        self.assertEqual(textproc.remove_filler_words("эээээ ну"), "ну")

    def test_capitalized_filler_gives_capital_to_next_word(self) -> None:
        self.assertEqual(textproc.remove_filler_words("Hmm, я не знаю"), "Я не знаю")
        self.assertEqual(textproc.remove_filler_words("Ээ, привет"), "Привет")

    def test_english_fillers_need_english_text(self) -> None:
        self.assertEqual(textproc.remove_filler_words("I um think so", "en"), "I think so")
        self.assertEqual(textproc.remove_filler_words("I um think so", "ru"), "I um think so")
        self.assertEqual(textproc.remove_filler_words("I um think so", "auto"), "I think so")

    def test_single_letter_is_not_removed(self) -> None:
        self.assertEqual(textproc.remove_filler_words("буква м"), "буква м")

    def test_custom_list_replaces_builtin(self) -> None:
        result = textproc.remove_filler_words("ээ привет", "ru", ["привет"])
        self.assertEqual(result, "ээ")

    def test_empty_text(self) -> None:
        self.assertEqual(textproc.remove_filler_words(""), "")


class StuttersTest(unittest.TestCase):
    def test_three_repeats_collapse(self) -> None:
        self.assertEqual(textproc.collapse_stutters("я я я думаю"), "я думаю")

    def test_two_repeats_stay(self) -> None:
        self.assertEqual(textproc.collapse_stutters("да да"), "да да")

    def test_numbers_are_not_stutters(self) -> None:
        self.assertEqual(textproc.collapse_stutters("1 1 1"), "1 1 1")

    def test_last_punctuation_is_kept(self) -> None:
        self.assertEqual(textproc.collapse_stutters("да да да."), "да.")

    def test_case_insensitive(self) -> None:
        self.assertEqual(textproc.collapse_stutters("Да да да"), "Да")


class NormalizeTest(unittest.TestCase):
    def test_spaces_and_punctuation(self) -> None:
        result = textproc.normalize_text("  привет ,  мир ( тест ) ! ")
        self.assertEqual(result, "привет, мир (тест)!")

    def test_empty(self) -> None:
        self.assertEqual(textproc.normalize_text("   "), "")


class ProcessTextTest(unittest.TestCase):
    def test_default_config_applies_fillers_and_stutters(self) -> None:
        cfg = Config()
        result = textproc.process_text("Ээ, я я я думаю", cfg)
        self.assertEqual(result, "Я думаю")

    def test_dictionary_before_fillers(self) -> None:
        cfg = Config(dictionary_words=("кубернетес",), trailing_space=True)
        result = textproc.process_text("Ээ, кубернетис я я я", cfg)
        self.assertEqual(result, "Кубернетес я ")

    def test_toggles_are_respected(self) -> None:
        cfg = Config(remove_fillers=False, collapse_stutters=False, trailing_space=False)
        self.assertEqual(textproc.process_text("ээ я я я", cfg), "ээ я я я")

    def test_empty_text_stays_empty(self) -> None:
        self.assertEqual(textproc.process_text("   ", Config(trailing_space=True)), "")


class DescribeRulesTest(unittest.TestCase):
    def test_empty_dictionary_is_reported(self) -> None:
        text = textproc.describe_rules(Config())
        self.assertIn("словарь пуст", text)
        self.assertIn("филлеры", text)

    def test_dictionary_count_and_threshold(self) -> None:
        cfg = Config(dictionary_words=("a", "b"), dictionary_threshold=0.25)
        self.assertIn("словарь 2 слов", textproc.describe_rules(cfg))
        self.assertIn("0.25", textproc.describe_rules(cfg))


if __name__ == "__main__":
    unittest.main()
