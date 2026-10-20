from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock

from PIL import Image

from image_matcher import MatchResult, TemplateMatcher
from tasks.weekly_flow import WeeklyFlowVision
from tasks.weekly_speed import WeeklySpeedReminder, speed_text


def lines(text, x=450, y=45):
    return [{'words':[{'text':text,'x':x,'y':y,'width':80,'height':25}]}]


class WeeklySpeedTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.path=Path(self.directory.name)/'frame.png'
        Image.new('RGB',(1000,300),(100,120,70)).save(self.path)
        self.runner=Mock(stop_event=threading.Event())
        self.vision=SimpleNamespace(_day_anchor=MatchResult(56,44,52,27,.99),matcher=Mock())
        self.vision.matcher.find_fast.side_effect=RuntimeError('not MAX')

    def tearDown(self):
        self.directory.cleanup()

    def test_speed_ocr_is_restricted_to_toolbar_and_handles_max_or_multipliers(self):
        for raw,expected in (('MAX','MAX'),('M A X','MAX'),('×1.0','×1'),('X2.0','×2'),('5.0','×5')):
            with self.subTest(raw=raw):
                self.assertEqual(speed_text(lines(raw)+lines('10',x=900),(420,25,600,90)),expected)
        self.assertIsNone(speed_text(lines('10'),(420,25,600,90)))

    def test_numeric_speed_warns_once_after_two_fresh_stable_views_without_clicking(self):
        worker=Mock()
        worker.recognize.return_value=lines('×5.0')
        factory=Mock(return_value=worker)
        reminder=WeeklySpeedReminder(ocr_factory=factory)
        reminder.observe(self.path,self.vision,self.runner)
        factory.assert_not_called()
        reminder.observe(self.path,self.vision,self.runner)
        reminder.observe(self.path,self.vision,self.runner)
        self.runner.warning.assert_called_once()
        self.assertIn('尚未设为MAX',self.runner.warning.call_args.args[0])
        self.assertIn('×5',self.runner.warning.call_args.args[0])
        self.runner.controller.tap.assert_not_called()
        worker.close.assert_called_once()

    def test_missing_ocr_is_nonfatal_and_does_not_claim_a_wrong_speed(self):
        reminder=WeeklySpeedReminder(ocr_factory=Mock(side_effect=RuntimeError('missing OCR')))
        reminder.observe(self.path,self.vision,self.runner)
        reminder.observe(self.path,self.vision,self.runner)
        self.assertTrue(reminder.finished)
        self.assertIn('无法确认',self.runner.warning.call_args.args[0])
        self.assertNotIn('尚未设为',self.runner.warning.call_args.args[0])

    def test_hidden_toolbar_and_changing_patch_do_not_warn(self):
        factory=Mock()
        reminder=WeeklySpeedReminder(ocr_factory=factory)
        self.vision._day_anchor=None
        reminder.observe(self.path,self.vision,self.runner)
        self.vision._day_anchor=MatchResult(56,44,52,27,.99)
        reminder.observe(self.path,self.vision,self.runner)
        Image.new('RGB',(1000,300),(200,200,200)).save(self.path)
        reminder.observe(self.path,self.vision,self.runner)
        factory.assert_not_called()
        self.runner.warning.assert_not_called()

    def test_actual_max_template_completes_without_starting_ocr_or_warning(self):
        root=Path(__file__).parents[1]
        with Image.open(root/'tests/fixtures/weekly-days-1.png') as source:
            image=Image.new('RGB',(1000,400),(35,45,50))
            image.paste(source,(20,20))
            image.save(self.path)
        vision=WeeklyFlowVision(TemplateMatcher(root/'templates'),[],[1.])
        self.assertEqual(vision.remaining_days(self.path),1)
        factory=Mock()
        reminder=WeeklySpeedReminder(ocr_factory=factory)
        reminder.observe(self.path,vision,self.runner)
        self.assertTrue(reminder.finished)
        factory.assert_not_called()
        self.runner.warning.assert_not_called()

    def test_ocr_max_result_does_not_warn_even_if_template_was_not_matched(self):
        worker=Mock()
        worker.recognize.return_value=lines('MAX')
        reminder=WeeklySpeedReminder(ocr_factory=Mock(return_value=worker))
        reminder.observe(self.path,self.vision,self.runner)
        reminder.observe(self.path,self.vision,self.runner)
        self.runner.warning.assert_not_called()
        worker.close.assert_called_once()


if __name__=='__main__':
    unittest.main()
