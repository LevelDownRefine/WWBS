"""Regression for the reported card modal, wrong-scale matches and FFT cost."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from image_matcher import TemplateMatcher, _fft_convolve_valid
from tasks.weekly_clicks import SKIP_TEMPLATES, WeeklyTarget, weekly_target_clickable, weekly_template_crop


class WeeklySkipTests(unittest.TestCase):
    def test_reported_modal_matches_skip_not_refresh_or_disabled_confirm(self):
        matcher = TemplateMatcher(Path(__file__).parents[1]/'templates')
        fixture = Path(__file__).parent/'fixtures'/'weekly-skip-modal.png'
        for ratio in (1, 1.5, 2):
            with self.subTest(ratio=ratio), tempfile.TemporaryDirectory() as directory:
                screen = Path(directory)/'screen.png'
                with Image.open(fixture) as source:
                    source.resize((round(source.width*ratio), round(source.height*ratio))).save(screen)
                for name in SKIP_TEMPLATES:
                    crop = weekly_template_crop(name, matcher.templates_dir)
                    result = matcher.find(screen, name, .5, [.833*ratio], first_match=True, max_width=1280,
                        template_crop=crop, candidate_validator=lambda result: weekly_target_clickable(
                            WeeklyTarget.read(screen, name, result, matcher.templates_dir, crop), result.score))
                    x, y = result.center
                    self.assertTrue(648*ratio < x < 894*ratio and 689*ratio < y < 752*ratio, (name, result))
                name = 'menu5.png'
                crop = weekly_template_crop(name, matcher.templates_dir)
                with self.assertRaises(RuntimeError):
                    matcher.find(screen, name, .5, [.833*ratio, .858*ratio], first_match=True, max_width=1280,
                        template_crop=crop, candidate_validator=lambda result: weekly_target_clickable(
                            WeeklyTarget.read(screen, name, result, matcher.templates_dir, crop), result.score))

    def test_invalid_first_scale_does_not_hide_later_clickable_candidate(self):
        from unittest.mock import patch
        from image_matcher import MatchResult
        matcher = TemplateMatcher(Path(__file__).parents[1]/'templates')
        fixture = Path(__file__).parent/'fixtures'/'weekly-skip-modal.png'
        candidates = [MatchResult(30, 30, 100, 50, .7), MatchResult(650, 700, 100, 50, .9)]
        with patch('image_matcher._match_single_scale_gray', side_effect=candidates) as match:
            result = matcher.find(fixture, 'menu6.png', .5, [1, .9], first_match=True,
                                  candidate_validator=lambda result: result.x > 600)
        self.assertEqual(result.center, (700, 725))
        self.assertEqual(match.call_count, 2)

    def test_padded_fft_matches_direct_convolution_for_odd_dimensions(self):
        rng = np.random.default_rng(14)
        image, kernel = rng.random((23, 31)), rng.random((7, 11))
        expected = np.array([[np.sum(image[y:y+7, x:x+11]*kernel[::-1, ::-1])
                              for x in range(21)] for y in range(17)])
        np.testing.assert_allclose(_fft_convolve_valid(image, kernel), expected, atol=1e-12)


if __name__ == '__main__':
    unittest.main()
