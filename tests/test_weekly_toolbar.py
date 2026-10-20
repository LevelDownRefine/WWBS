"""MAX / x5.0 must never be treated as the orange close button."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from PIL import Image

from image_matcher import MatchResult, TemplateMatcher
from tasks.weekly_clicks import WeeklyTarget, weekly_target_clickable, weekly_template_crop
from tasks.weekly_flow import WeeklyFlowVision
from windows_client import ClientWindowController, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
import windows_client


TEMPLATES=Path(__file__).parents[1]/'templates'
FIXTURES=Path(__file__).parent/'fixtures'


class WeeklyToolbarTests(unittest.TestCase):
    def test_reported_max_toolbar_is_not_close_at_problematic_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'frame.png'
            for day,ratio in ((1,2.),(4,1.5),(4,2.)):
                with self.subTest(day=day,ratio=ratio), Image.open(FIXTURES/f'weekly-days-{day}.png') as source:
                    source=source.resize((round(source.width*ratio),round(source.height*ratio)))
                    frame=Image.new('RGB',(max(1100,source.width+60),400),(35,45,50))
                    frame.paste(source,(20,20))
                    frame.save(path)
                    vision=WeeklyFlowVision(TemplateMatcher(TEMPLATES),['menu95.png'],[1.,.97,1.03,.94,1.06])
                    self.assertIsNone(vision.detect(path,'close',wide=True))

    def test_actual_close_and_next_stage_text_survive_scaling(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'frame.png'
            for name,kind in (('menu95.png','close'),('menu93.png','next_stage')):
                for ratio in (.75,1.,1.5,2.):
                    with self.subTest(name=name,ratio=ratio), Image.open(TEMPLATES/name) as source:
                        source=source.resize((round(source.width*ratio),round(source.height*ratio)))
                        frame=Image.new('RGB',(1920,1080),(35,45,50))
                        frame.paste(source,(900,420))
                        frame.save(path)
                        vision=WeeklyFlowVision(TemplateMatcher(TEMPLATES),[name],[ratio])
                        page=vision.detect(path,kind)
                        self.assertIsNotNone(page)
                        self.assertEqual(page.kind,kind)
                        self.assertTrue(900 <= page.match.center[0] < 900+source.width)

    def test_native_caption_check_rejects_border_only_match(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'frame.png'
            with Image.open(TEMPLATES/'menu95.png') as image:
                frame=image.convert('RGB')
            # A flat orange interior retains button colour but no close glyphs.
            crop=weekly_template_crop('menu95.png',TEMPLATES)
            frame.paste((215,151,59),crop)
            frame.save(path)
            x,y,right,bottom=crop
            target=WeeklyTarget.read(path,'menu95.png',MatchResult(x,y,right-x,bottom-y,.99),TEMPLATES,crop)
            self.assertFalse(weekly_target_clickable(target,.99))

    def test_reported_x5_photo_does_not_hide_visible_next_day(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'frame.png'
            frame=Image.new('RGB',(1920,1080),(35,45,50))
            with Image.open(FIXTURES/'weekly-speed-x5-photo.png') as speed:
                frame.paste(speed,(1210,20))
            with Image.open(TEMPLATES/'menu5.png') as next_day:
                frame.paste(next_day,(1300,850))
            frame.save(path)
            vision=WeeklyFlowVision(TemplateMatcher(TEMPLATES),['menu95.png','menu5.png','menu93.png'],[1.])
            page=vision.detect(path,'close',wide=True)
            self.assertIsNotNone(page)
            self.assertEqual(page.kind,'next_day')
            self.assertGreater(page.match.center[0],1300)
            self.assertGreater(page.match.center[1],850)

    def test_one_tap_does_not_send_three_independent_clicks(self):
        controller=ClientWindowController.__new__(ClientWindowController)
        controller._ensure_window=Mock()
        controller.screenshot_to_client=Mock(return_value=(1288,56))
        controller._screenshot_point_to_desktop=Mock(return_value=(1284,487))
        controller._clamp_to_virtual_screen=Mock(return_value=(1284,487))
        controller._focus_window=Mock()
        controller._set_cursor_with_dpi_fallback=Mock(return_value=(True,1284,487,'SendInputAbsolute'))
        controller.cursor_position=Mock(return_value=(1284,487))
        controller._send_mouse_button=Mock()
        controller._post_client_click=Mock()
        controller.last_capture_size=(1920,1080)
        controller.last_screen_bbox=(-4,431,1916,1511)
        with patch.object(windows_client.user32,'mouse_event') as legacy, patch('windows_client.time.sleep'):
            controller.tap(1288,56)
        self.assertEqual(controller._send_mouse_button.call_args_list,[call(MOUSEEVENTF_LEFTDOWN),call(MOUSEEVENTF_LEFTUP)])
        controller._post_client_click.assert_not_called()
        legacy.assert_not_called()


if __name__=='__main__':
    unittest.main()
