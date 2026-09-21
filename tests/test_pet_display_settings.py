import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from app import App


class PetDisplaySettingsTests(unittest.TestCase):
    def test_pet_size_accepts_percent_text(self):
        self.assertEqual(App._normalize_pet_size_percent("85%"), 85)
        self.assertEqual(App._normalize_pet_size_percent("115"), 115)

    def test_pet_size_falls_back_and_clamps(self):
        self.assertEqual(App._normalize_pet_size_percent("not-a-size"), 100)
        self.assertEqual(App._normalize_pet_size_percent(10), 60)
        self.assertEqual(App._normalize_pet_size_percent(999), 160)

    def test_pet_visibility_defaults_to_visible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Path(temp_dir) / "missing.json"
            with patch.object(app, "PET_DISPLAY_CONFIG", settings):
                self.assertTrue(App._load_pet_visible())

    def test_pet_visibility_is_restored_and_saved_without_losing_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Path(temp_dir) / "pet-display-settings.json"
            settings.write_text(json.dumps({"percent": 115, "visible": False}), encoding="utf-8")
            instance = App.__new__(App)
            with patch.object(app, "PET_DISPLAY_CONFIG", settings):
                self.assertFalse(App._load_pet_visible())
                instance._save_pet_display_settings(visible=True)
                saved = json.loads(settings.read_text(encoding="utf-8"))

        self.assertEqual(saved, {"percent": 115, "visible": True})

    def test_pet_behavior_defaults_are_feature_specific(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Path(temp_dir) / "missing.json"
            with patch.object(app, "PET_DISPLAY_CONFIG", settings):
                self.assertTrue(
                    App._load_pet_feature_enabled("jingran", "look_at_pointer", True)
                )
                self.assertTrue(
                    App._load_pet_feature_enabled("jingran", "auto_jump", True)
                )

    def test_saved_auto_jump_setting_overrides_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Path(temp_dir) / "pet-display-settings.json"
            settings.write_text(
                json.dumps({"auto_jump": {"jingran": False}}),
                encoding="utf-8",
            )
            with patch.object(app, "PET_DISPLAY_CONFIG", settings):
                self.assertFalse(
                    App._load_pet_feature_enabled("jingran", "auto_jump", True)
                )

    def test_pet_behavior_is_saved_per_character(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Path(temp_dir) / "pet-display-settings.json"
            settings.write_text(json.dumps({"percent": 115}), encoding="utf-8")
            instance = App.__new__(App)
            instance.pet_id = "jingran"
            with patch.object(app, "PET_DISPLAY_CONFIG", settings):
                instance._save_pet_feature_enabled("look_at_pointer", False)
                instance.pet_id = "cartethyia"
                instance._save_pet_feature_enabled("look_at_pointer", True)
                saved = json.loads(settings.read_text(encoding="utf-8"))

        self.assertEqual(saved["percent"], 115)
        self.assertEqual(
            saved["look_at_pointer"],
            {"jingran": False, "cartethyia": True},
        )


if __name__ == "__main__":
    unittest.main()
