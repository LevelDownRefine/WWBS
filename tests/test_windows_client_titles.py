import unittest

from windows_client import ClientWindowController, DEFAULT_GAME_WINDOW_TITLES


class WindowTitleDetectionTests(unittest.TestCase):
    def test_auto_mode_supports_simplified_traditional_and_global_titles(self):
        self.assertEqual(ClientWindowController._expand_title_keywords("自动"), DEFAULT_GAME_WINDOW_TITLES)
        self.assertEqual(ClientWindowController._expand_title_keywords("鸣潮"), DEFAULT_GAME_WINDOW_TITLES)
        self.assertEqual(ClientWindowController._expand_title_keywords("鳴潮"), DEFAULT_GAME_WINDOW_TITLES)
        self.assertEqual(ClientWindowController._expand_title_keywords("Wuthering Waves"), DEFAULT_GAME_WINDOW_TITLES)

        keywords = ClientWindowController._expand_title_keywords("自动")
        self.assertEqual(ClientWindowController._title_match_kind("鳴潮", keywords), "exact")

    def test_global_steam_title_matches_case_insensitively(self):
        keywords = ClientWindowController._expand_title_keywords("自动")
        self.assertEqual(ClientWindowController._title_match_kind("Wuthering Waves", keywords), "exact")
        self.assertEqual(ClientWindowController._title_match_kind("WUTHERING WAVES", keywords), "exact")

    def test_exact_game_title_is_preferred_over_partial_title(self):
        keywords = ClientWindowController._expand_title_keywords("自动")
        self.assertEqual(ClientWindowController._title_match_kind("Wuthering Waves", keywords), "exact")
        self.assertEqual(ClientWindowController._title_match_kind("Wuthering Waves on Steam", keywords), "partial")

    def test_custom_title_and_multiple_manual_titles_are_supported(self):
        self.assertEqual(ClientWindowController._expand_title_keywords("Custom Client"), ("Custom Client",))
        self.assertEqual(
            ClientWindowController._expand_title_keywords("Custom One | Custom Two"),
            ("Custom One", "Custom Two"),
        )

    def test_tiny_same_name_window_is_not_a_game_candidate(self):
        self.assertFalse(ClientWindowController._is_plausible_game_size(199, 34))
        self.assertTrue(ClientWindowController._is_plausible_game_size(1280, 720))

    def test_real_unreal_game_window_outranks_same_title_helper(self):
        game = ClientWindowController._candidate_sort_key("exact", 1280, 720, "UnrealWindow")
        helper = ClientWindowController._candidate_sort_key("exact", 1920, 1080, "Chrome_WidgetWin_1")
        self.assertGreater(game, helper)


if __name__ == "__main__":
    unittest.main()
