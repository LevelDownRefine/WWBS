import unittest

from app import App


class PetDisplaySettingsTests(unittest.TestCase):
    def test_pet_size_accepts_percent_text(self):
        self.assertEqual(App._normalize_pet_size_percent("85%"), 85)
        self.assertEqual(App._normalize_pet_size_percent("115"), 115)

    def test_pet_size_falls_back_and_clamps(self):
        self.assertEqual(App._normalize_pet_size_percent("not-a-size"), 100)
        self.assertEqual(App._normalize_pet_size_percent(10), 60)
        self.assertEqual(App._normalize_pet_size_percent(999), 160)


if __name__ == "__main__":
    unittest.main()
