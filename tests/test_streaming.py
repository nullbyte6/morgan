import unittest

from src.init.streaming import SpeechBuffer


class SpeechBufferTests(unittest.TestCase):
    def test_first_phrase_is_released_without_waiting_for_sixty_characters(self):
        buffer = SpeechBuffer()

        phrases = buffer.feed(
            "Esta es una respuesta inicial que puede empezar a reproducirse pronto")

        self.assertEqual(phrases, ["Esta es una respuesta inicial que puede"])
        self.assertLessEqual(len(phrases[0]), buffer.FIRST_PHRASE_LIMIT)

    def test_first_phrase_prefers_early_punctuation(self):
        buffer = SpeechBuffer()

        phrases = buffer.feed("Aquí tienes la respuesta, seguida de más detalles")

        self.assertEqual(phrases, ["Aquí tienes la respuesta,"])

    def test_later_phrases_still_wait_for_strong_punctuation(self):
        buffer = SpeechBuffer()
        buffer.feed(
            "Esta es una respuesta inicial que puede empezar a reproducirse pronto")

        self.assertEqual(buffer.feed(
            ", aunque tenga una coma intermedia y continúe"), [])
        self.assertEqual(buffer.feed(" hasta terminar."), [])
        self.assertEqual(buffer.finish(), [
            "empezar a reproducirse pronto, aunque tenga una coma "
            "intermedia y continúe hasta terminar."])


if __name__ == "__main__":
    unittest.main()
