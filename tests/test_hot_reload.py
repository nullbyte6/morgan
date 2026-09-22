import unittest

from src.init.hot_reload import is_reload_command


class ReloadCommandTests(unittest.TestCase):
    def test_accepts_short_reload_commands(self):
        for command in ("ref", "reload", "/reload", "recarga", "recargar"):
            with self.subTest(command=command):
                self.assertTrue(is_reload_command(command))

    def test_accepts_explicit_style_reload_requests(self):
        for command in (
                "Recarga la hoja de estilos",
                "recargar estilos",
                "reload stylesheet",
                "recarga Arlo"):
            with self.subTest(command=command):
                self.assertTrue(is_reload_command(command))

    def test_does_not_capture_questions_about_reloading(self):
        for command in (
                "¿Cómo funciona el hot reload?",
                "No recargues el código",
                "Quiero cambiar los estilos"):
            with self.subTest(command=command):
                self.assertFalse(is_reload_command(command))


if __name__ == "__main__":
    unittest.main()
