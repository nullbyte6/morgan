import unittest

from src.init.config import DEFAULTS, validate_config
from src.init.speech_text import prepare_speech


class SpeechTextTests(unittest.TestCase):
    def test_windows_path_omits_separators_and_spells_initialisms(self):
        spoken = prepare_speech(r"src\init\editor\live.py")

        self.assertEqual(
            spoken,
            "ese erre ce, init, editor, live punto pe i griega",
        )
        self.assertNotIn("barra", spoken)
        self.assertNotIn("\\", spoken)

    def test_unix_path_uses_the_same_pronunciation(self):
        windows = prepare_speech(r"src\init\editor\live.py")
        unix = prepare_speech("src/init/editor/live.py")

        self.assertEqual(unix, windows)

    def test_words_are_not_spelled(self):
        spoken = prepare_speech("assets/fonts/editor.py")

        self.assertEqual(spoken, "assets, fonts, editor punto pe i griega")

    def test_non_path_slashes_are_preserved(self):
        self.assertEqual(prepare_speech("and/or 1/2"), "and/or 1/2")

    def test_custom_pronunciation_is_applied_after_path_expansion(self):
        spoken = prepare_speech(
            r"src\init\editor\live.py",
            {"live": "laiv"},
        )

        self.assertEqual(
            spoken,
            "ese erre ce, init, editor, laiv punto pe i griega",
        )

    def test_pronunciation_config_is_validated(self):
        config = {**DEFAULTS, "pronunciations": {"live": "laiv"}}

        self.assertEqual(validate_config(config)["pronunciations"], {"live": "laiv"})

        with self.assertRaises(ValueError):
            validate_config({**DEFAULTS, "pronunciations": {"": ""}})


if __name__ == "__main__":
    unittest.main()
