from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from image_matcher import TemplateMatcher, _fft_convolve_valid


class ImageMatcherTests(unittest.TestCase):
    def test_fast_match_supports_cropped_search_region_and_returns_full_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            templates = root / "templates"
            templates.mkdir()
            screenshot = Image.new("RGB", (800, 500), (20, 25, 30))
            patch = Image.new("RGB", (90, 45), (230, 230, 230))
            draw = ImageDraw.Draw(patch)
            draw.rectangle((8, 8, 35, 35), fill=(25, 25, 25))
            draw.ellipse((48, 8, 80, 37), fill=(90, 90, 90))
            patch.save(templates / "prompt.png")
            screenshot.paste(patch, (610, 310))
            screenshot_path = root / "screen.png"
            screenshot.save(screenshot_path)

            result = TemplateMatcher(templates).find_fast(
                screenshot_path,
                "prompt.png",
                threshold=0.90,
                region=(400, 200, 790, 490),
            )

            self.assertEqual((result.x, result.y), (610, 310))

    def test_numpy_fft_matches_direct_valid_convolution(self) -> None:
        rng = np.random.default_rng(137)
        image = rng.random((9, 11))
        kernel = rng.random((3, 4))
        actual = _fft_convolve_valid(image, kernel)
        expected = np.empty((7, 8))
        flipped = kernel[::-1, ::-1]
        for y in range(expected.shape[0]):
            for x in range(expected.shape[1]):
                expected[y, x] = np.sum(image[y : y + 3, x : x + 4] * flipped)
        np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10)

    def test_template_matcher_finds_exact_patch_without_scipy(self) -> None:
        rng = np.random.default_rng(137)
        screenshot = rng.integers(0, 256, size=(80, 120, 3), dtype=np.uint8)
        x, y, width, height = 47, 29, 24, 18
        template = screenshot[y : y + height, x : x + width]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot_path = root / "screen.png"
            template_path = root / "target.png"
            Image.fromarray(screenshot).save(screenshot_path)
            Image.fromarray(template).save(template_path)
            result = TemplateMatcher(root).find(screenshot_path, template_path.name, threshold=0.99, scales=[1.0])
        self.assertEqual((result.x, result.y), (x, y))
        self.assertGreater(result.score, 0.999)

    def test_fast_template_matcher_finds_exact_patch(self) -> None:
        rng = np.random.default_rng(731)
        screenshot = rng.integers(0, 256, size=(240, 400, 3), dtype=np.uint8)
        x, y, width, height = 173, 91, 70, 42
        template = screenshot[y : y + height, x : x + width]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot_path = root / "screen.png"
            template_path = root / "target.png"
            Image.fromarray(screenshot).save(screenshot_path)
            Image.fromarray(template).save(template_path)
            result = TemplateMatcher(root).find_fast(
                screenshot_path,
                template_path.name,
                threshold=0.95,
                scale=1.0,
                max_width=400,
            )
        self.assertEqual((result.x, result.y), (x, y))
        self.assertGreater(result.score, 0.999)

    def test_scaled_matching_supports_common_16_by_9_resolutions(self) -> None:
        rng = np.random.default_rng(1080)
        base_width, base_height = 384, 216
        screenshot = rng.integers(0, 256, size=(base_height, base_width, 3), dtype=np.uint8)
        x, y, width, height = 167, 79, 66, 42
        template = screenshot[y : y + height, x : x + width]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template_path = root / "target.png"
            Image.fromarray(template).save(template_path)
            for scale in (1600 / 1920, 1536 / 1920, 1280 / 1920):
                screenshot_path = root / f"screen-{scale:.3f}.png"
                scaled_size = (round(base_width * scale), round(base_height * scale))
                Image.fromarray(screenshot).resize(scaled_size, Image.Resampling.LANCZOS).save(screenshot_path)
                result = TemplateMatcher(root).find(
                    screenshot_path,
                    template_path.name,
                    threshold=0.82,
                    scales=[scale, scale * 0.97, scale * 1.03],
                )
                self.assertAlmostEqual(result.x, round(x * scale), delta=2)
                self.assertAlmostEqual(result.y, round(y * scale), delta=2)
                self.assertGreaterEqual(result.score, 0.82)


if __name__ == "__main__":
    unittest.main()
