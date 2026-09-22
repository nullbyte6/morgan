import unittest

from src.init.subtitle_timing import StreamingWordTimeline, WordTimeline


class WordTimelineTests(unittest.TestCase):
    def test_maps_audio_offsets_to_individual_words(self):
        timeline = WordTimeline("uno dos tres", 900)

        self.assertEqual(timeline.word_at(0), "uno")
        self.assertEqual(timeline.word_at(300), "dos")
        self.assertEqual(timeline.word_at(600), "tres")

    def test_preserves_punctuation_on_the_displayed_word(self):
        timeline = WordTimeline("Hola, mundo!", 1200)

        self.assertEqual(timeline.word_at(0), "Hola,")
        self.assertEqual(timeline.word_at(1199), "mundo!")

    def test_reveals_the_phrase_through_the_current_word(self):
        timeline = WordTimeline("uno dos tres", 900)

        self.assertEqual(timeline.text_at(0), "uno")
        self.assertEqual(timeline.text_at(300), "uno dos")
        self.assertEqual(timeline.text_at(600), "uno dos tres")

    def test_revealed_phrase_keeps_repeated_words(self):
        timeline = WordTimeline("muy muy bien", 1000)

        self.assertEqual(timeline.text_at(500), "muy muy")

    def test_punctuation_reserves_more_time_for_a_pause(self):
        timeline = WordTimeline("sí, vale", 1000)

        self.assertEqual(timeline.word_at(450), "sí,")
        self.assertEqual(timeline.word_at(650), "vale")

    def test_empty_text_or_audio_has_no_current_word(self):
        self.assertEqual(WordTimeline("", 100).word_at(0), "")
        self.assertEqual(WordTimeline("hola", 0).word_at(0), "")
        self.assertEqual(WordTimeline("", 100).text_at(0), "")

    def test_offsets_are_clamped_to_the_timeline(self):
        timeline = WordTimeline("primera última", 500)

        self.assertEqual(timeline.word_at(-20), "primera")
        self.assertEqual(timeline.word_at(999), "última")


class StreamingWordTimelineTests(unittest.TestCase):
    def test_reveals_text_before_the_final_duration_is_known(self):
        timeline = StreamingWordTimeline(
            "uno dos tres", sample_rate=100, characters_per_second=3)

        self.assertEqual(timeline.text_at(0), "uno")
        self.assertEqual(timeline.text_at(100), "uno dos")

    def test_final_duration_refines_remaining_word_timing(self):
        timeline = StreamingWordTimeline(
            "uno dos tres", sample_rate=100, characters_per_second=3)
        timeline.finalize(900)

        self.assertEqual(timeline.text_at(0), "uno")
        self.assertEqual(timeline.text_at(300), "uno dos")
        self.assertEqual(timeline.text_at(600), "uno dos tres")

    def test_finalization_never_hides_already_revealed_words(self):
        timeline = StreamingWordTimeline(
            "uno dos tres", sample_rate=100, characters_per_second=3)

        self.assertEqual(timeline.text_at(200), "uno dos tres")
        timeline.finalize(900)
        self.assertEqual(timeline.text_at(100), "uno dos tres")


if __name__ == "__main__":
    unittest.main()
