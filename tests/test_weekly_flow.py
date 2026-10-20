import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import app
from image_matcher import MatchResult, TemplateMatcher
from weekly_clicks import WeeklyTarget, weekly_template_crop
from weekly_flow import CardDecision, FAMILIES, Page, WeeklyFlowVision, family, run_weekly_flow


class WeeklyFlowVisionTests(unittest.TestCase):
    def test_reported_day_bars_use_trailing_amber_dots_at_multiple_scales(self):
        for day in (1, 4):
            for scale in (.75, 1., 1.5):
                with self.subTest(day=day, scale=scale), tempfile.TemporaryDirectory() as directory:
                    source = Image.open(Path(__file__).parent/'fixtures'/f'weekly-days-{day}.png')
                    frame = Image.new('RGB', (1800, 1000), (30, 35, 30))
                    frame.paste(source.resize((round(source.width*scale), round(source.height*scale))), (200, 15))
                    path = Path(directory)/'frame.png'
                    frame.save(path)
                    vision = WeeklyFlowVision(TemplateMatcher(app.TEMPLATES_DIR), ['menu4.png'], [scale])
                    self.assertEqual(vision.remaining_days(path), day)
                    # Cached text anchor still reads the current dots every time.
                    self.assertEqual(vision.remaining_days(path), day)

    def test_every_stock_template_is_classified_by_action_not_ordinal_position(self):
        names = [name for group in FAMILIES.values() for name in group]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'frame.png'
            for name in names:
                with self.subTest(template=name), Image.open(app.TEMPLATES_DIR/name) as source:
                    frame = Image.new('RGB', (900, 600), (35, 45, 55))
                    frame.paste(source, (220, 270))
                    frame.save(path)
                    vision = WeeklyFlowVision(TemplateMatcher(app.TEMPLATES_DIR), names, [1.])
                    page = vision.detect(path, 'start')
                    self.assertIsNotNone(page)
                    self.assertEqual(page.kind, family(name), (name, page))


class WeeklyFlowRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = 0.
        self.runner = app.TaskRunner(Mock(spec=['tap']), Mock(), dry_run=False)
        self.runner.template_root = self.root/'templates'
        self.runner.template_root.mkdir()
        self.runner.max_cycles = 1
        self.runner._check_weekly_cap = Mock()
        self.runner._ensure_weekly_skill_selected = Mock()
        self.runner._fast_scales = lambda: [.833, 1.]
        self.runner._weekly_monitoring = True
        self.runner._sleep_interruptible = lambda duration: self.advance(duration)
        self.runner._sleep_click_interval = lambda duration: self.advance(duration)
        fixture = Path(__file__).parent/'fixtures'/'weekly-skip-modal.png'
        original = Image.open(fixture).convert('RGB')
        changed = original.copy()
        ImageDraw.Draw(changed).rectangle((140, 190, 380, 300), fill=(45, 60, 70))
        ImageDraw.Draw(changed).rectangle((520, 190, 750, 300), fill=(45, 60, 70))
        self.frames = [original, changed]
        self.pages = []
        vision = WeeklyFlowVision(TemplateMatcher(app.TEMPLATES_DIR), ['menu4.png'], [.833])
        for index, frame in enumerate(self.frames):
            path = self.root/f'{index}.png'
            frame.save(path)
            page = vision.detect(path, 'skip')
            self.assertIsNotNone(page.cards)
            self.pages.append(page)
        for name in ('menu95.png', 'menu99.png'):
            frame = Image.new('RGB', original.size, (35, 45, 55))
            with Image.open(app.TEMPLATES_DIR/name) as picture:
                frame.paste(picture, (600, 700))
                match = MatchResult(600, 700, picture.width, picture.height, 1.)
            path = self.root/f'{name}.png'
            frame.save(path)
            target = WeeklyTarget.read(path, name, match, app.TEMPLATES_DIR, weekly_template_crop(name, app.TEMPLATES_DIR))
            self.frames.append(frame)
            self.pages.append(Page(name, family(name), match, target))
        self.index = 0
        self.taps = []
        self.runner._capture_for_matching = self.capture
        self.runner.controller.tap.side_effect = self.tap

    def tearDown(self):
        self.tmp.cleanup()

    def advance(self, duration):
        self.now += duration

    def capture(self, path):
        self.advance(.03)
        self.frames[self.index].save(path)

    def tap(self, x, y):
        page = self.pages[self.index]
        self.assertTrue(page.target.box[0] <= x < page.target.box[2])
        self.assertTrue(page.target.box[1] <= y < page.target.box[3])
        self.taps.append((self.index, self.now))
        self.index = min(self.index+1, len(self.frames)-1)

    def run_flow(self, *, real_vision=False):
        vision = Mock()
        vision.detect.side_effect = lambda *_args, **_options: self.pages[self.index]
        factory = WeeklyFlowVision if real_vision else Mock(return_value=vision)
        with patch('weekly_flow.WeeklyFlowVision', side_effect=factory), \
                patch('weekly_flow.time.monotonic', side_effect=lambda: self.now):
            run_weekly_flow(self.runner, app.Step(action='tap_image', template='menu1.png'),
                            app.Step(action='tap_image_cycle', templates=['menu4.png', 'menu95.png', 'menu99.png']))
        return vision

    def test_real_classifier_resumes_and_follows_changed_pages_with_cached_scales(self):
        self.run_flow(real_vision=True)
        self.assertEqual([index for index, _ in self.taps], [0, 1, 2])
        self.runner._ensure_weekly_skill_selected.assert_not_called()

    def test_resume_on_skip_repeat_new_cards_then_jump_to_non_adjacent_page(self):
        self.assertTrue(self.pages[1].cards.changed_from(self.pages[0].cards))
        self.run_flow()
        self.assertEqual([index for index, _ in self.taps], [0, 1, 2])
        self.assertLess(self.taps[1][1]-self.taps[0][1], 1.5)
        self.runner._ensure_weekly_skill_selected.assert_not_called()
        self.assertEqual(self.index, 3)  # Stop on final settlement, do not start an extra round.

    def test_unchanged_skip_is_not_clicked_repeatedly_or_counted_as_next_day(self):
        self.runner.controller.tap.side_effect = lambda *_args: self.taps.append((0, self.now))
        with self.assertRaisesRegex(RuntimeError, '仍无响应'):
            self.run_flow()
        self.assertEqual(len(self.taps), 3)
        self.assertGreaterEqual(self.taps[1][1]-self.taps[0][1], 4)

    def test_background_only_changes_cannot_acknowledge_new_cards(self):
        image = self.frames[0].copy()
        ImageDraw.Draw(image).rectangle((0, 760, 1278, 899), fill='white')
        path = self.root/'background.png'
        image.save(path)
        current = CardDecision.read(path, self.pages[0].target)
        self.assertFalse(current.changed_from(self.pages[0].cards))

    def test_fade_lasting_more_than_five_probes_relocates_without_blind_clicks(self):
        vision = Mock()
        # Both initial loading and post-click loading can exceed five fast probes.
        calls = {}
        def detect(*_args, **_options):
            calls[self.index] = calls.get(self.index, 0)+1
            return None if calls[self.index] < 40 else self.pages[self.index]
        vision.detect.side_effect = detect
        with patch('weekly_flow.WeeklyFlowVision', return_value=vision), \
                patch('weekly_flow.time.monotonic', side_effect=lambda: self.now):
            run_weekly_flow(self.runner, app.Step(action='tap_image', template='menu1.png'),
                            app.Step(action='tap_image_cycle', templates=['menu4.png', 'menu95.png', 'menu99.png']))
        self.assertEqual([index for index, _ in self.taps], [0, 1, 2])
        self.assertGreater(self.taps[0][1], 4)
        self.assertGreater(self.taps[1][1]-self.taps[0][1], 4)

    def test_unknown_page_stops_after_bounded_relocation_without_clicking(self):
        vision = Mock()
        vision.detect.return_value = None
        with patch('weekly_flow.WeeklyFlowVision', return_value=vision), \
                patch('weekly_flow.time.monotonic', side_effect=lambda: self.now):
            with self.assertRaisesRegex(RuntimeError, '20秒'):
                run_weekly_flow(self.runner, app.Step(action='tap_image', template='menu1.png'),
                                app.Step(action='tap_image_cycle', templates=['menu4.png']))
        self.assertEqual(self.taps, [])
        self.assertLess(self.now, 21)


if __name__ == '__main__':
    unittest.main()
