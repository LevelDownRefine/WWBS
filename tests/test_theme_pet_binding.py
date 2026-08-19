from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as app_module
from app import App


class ThemePetBindingTests(unittest.TestCase):
    @staticmethod
    def _app(theme_id: str, pet_id: str) -> App:
        instance = App.__new__(App)
        instance.root = object()
        instance.theme_id = theme_id
        instance.pet_id = pet_id
        instance._theme_pack_valid = Mock(return_value=True)
        instance._restart_app = Mock()
        return instance

    def test_character_theme_writes_matching_pet(self) -> None:
        instance = self._app("daniya", "daniya")
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            pet_config = Path(directory) / "pet.json"
            with (
                patch.object(app_module, "THEME_CONFIG", theme_config),
                patch.object(app_module, "PET_CONFIG", pet_config),
                patch.object(app_module.messagebox, "askyesno", return_value=False),
            ):
                instance._select_theme("aemeath")
            self.assertEqual(json.loads(theme_config.read_text(encoding="utf-8"))["theme"], "aemeath")
            self.assertEqual(json.loads(pet_config.read_text(encoding="utf-8"))["pet"], "aemeath")

    def test_pet_writes_matching_character_theme(self) -> None:
        instance = self._app("simple", "daniya")
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            pet_config = Path(directory) / "pet.json"
            with (
                patch.object(app_module, "THEME_CONFIG", theme_config),
                patch.object(app_module, "PET_CONFIG", pet_config),
                patch.object(app_module.messagebox, "askyesno", return_value=False),
            ):
                instance._select_pet("aemeath")
            self.assertEqual(json.loads(theme_config.read_text(encoding="utf-8"))["theme"], "aemeath")
            self.assertEqual(json.loads(pet_config.read_text(encoding="utf-8"))["pet"], "aemeath")

    def test_simple_theme_keeps_current_pet(self) -> None:
        instance = self._app("aemeath", "aemeath")
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            pet_config = Path(directory) / "pet.json"
            with (
                patch.object(app_module, "THEME_CONFIG", theme_config),
                patch.object(app_module, "PET_CONFIG", pet_config),
                patch.object(app_module.messagebox, "askyesno", return_value=False),
            ):
                instance._select_theme("simple")
            self.assertEqual(json.loads(theme_config.read_text(encoding="utf-8"))["theme"], "simple")
            self.assertFalse(pet_config.exists())


if __name__ == "__main__":
    unittest.main()
