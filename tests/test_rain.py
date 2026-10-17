import ctypes
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import app
from boss_rain import BossRainGate, boss_bar_present, passive_boss_sample
from local_settings import convert_settings
from rain_effect import RainScene, normalize_rain_settings, premultiplied_bgra
from rain_music import RainMusic
from rain_overlay import LayeredRainSurface, RAIN_WINDOW_STYLE


class RainTests(unittest.TestCase):
    def test_default_is_off_and_import_keeps_appearance_and_volume(self):
        self.assertEqual(normalize_rain_settings(None)['mode'], '关闭')
        data = convert_settings('rain-settings.json', {'mode':'Boss战自动', 'level':'大雨', 'strength':'明显','volume':50})
        self.assertEqual(data, {'mode':'Boss战自动','level':'大雨','strength':'明显','volume':50})

    def test_scene_is_transparent_and_moves_without_a_background_screenshot(self):
        scene = RainScene(480, 270, seed=34)
        before, after = scene.frame(0), scene.frame(.1)
        pixels = np.asarray(after)
        self.assertGreater(np.mean(pixels[:,:,3] == 0), .9)
        self.assertGreater(pixels[:,:,3].max(), 0)
        self.assertFalse(np.array_equal(np.asarray(before), pixels))
        bgra = np.frombuffer(premultiplied_bgra(after), dtype=np.uint8).reshape(270,480,4)
        self.assertTrue(np.all(bgra[:,:,:3] <= bgra[:,:,3:4]))

    def test_top_long_bar_includes_empty_track_and_small_remaining_health(self):
        for size in ((1920,1080), (1280,720), (2560,1440)):
            width, height = size
            for remaining in (0., .1, .5, 1.):
                with self.subTest(size=size,remaining=remaining):
                    image = np.full((height,width,3), 30, dtype=np.uint8)
                    y, left, right = round(height*.052), round(width*.32), round(width*.68)
                    thickness = max(3, round(height*.004))
                    image[y:y+thickness,left:right] = (180,180,180)
                    image[y:y+thickness,left:left+round((right-left)*remaining)] = (218,75,58)
                    lower = y+round(height*.019)
                    image[lower:lower+thickness,left:right] = (215,215,215)
                    self.assertTrue(boss_bar_present(Image.fromarray(image)))

    def test_bright_scene_small_enemy_bar_and_bottom_player_bar_do_not_trigger(self):
        bright = np.full((1080,1920,3),210,dtype=np.uint8)
        self.assertFalse(boss_bar_present(Image.fromarray(bright)))
        image = np.full((1080,1920,3),30,dtype=np.uint8)
        image[54:59,920:1040] = (220,80,60)
        image[880:887,650:1270] = (220,80,60)
        self.assertFalse(boss_bar_present(Image.fromarray(image)))

    def test_reported_boss_bar_at_native_and_scaled_resolutions(self):
        with Image.open(Path(__file__).parent/'fixtures'/'boss-rain-top-bar.png') as source:
            for width, height in ((2560,1440), (1920,1080), (1280,720)):
                with self.subTest(size=(width,height)):
                    strip = source.resize((width, round(height*.11)), Image.Resampling.LANCZOS)
                    self.assertTrue(boss_bar_present(strip, (width,height)))
                    # A nearly empty main track still has the same two-track HUD.
                    strip.paste((40,75,80), (round(width*.34),round(height*.047),
                                           round(width*.67),round(height*.065)))
                    self.assertFalse(boss_bar_present(strip, (width,height)))
                    strip.paste((175,175,175), (round(width*.355),round(height*.054),
                                              round(width*.645),round(height*.059)))
                    strip.paste((218,75,58), (round(width*.355),round(height*.054),
                                            round(width*.370),round(height*.059)))
                    self.assertTrue(boss_bar_present(strip, (width,height)))
                    # A name, the minimap and the scene without either bar are insufficient.
                    strip.paste((40,75,80), (round(width*.34),round(height*.065),
                                           round(width*.67),round(height*.080)))
                    self.assertFalse(boss_bar_present(strip, (width,height)))

    def test_mob_bars_cannot_trigger_boss_rain_even_when_long_and_at_top(self):
        for width,height in ((1280,720),(1920,1080),(2560,1440)):
            for left,right in ((.32,.68),(.20,.52),(.43,.56)):
                for white_track in (False,True):
                    with self.subTest(size=(width,height),left=left,white_track=white_track):
                        pixels = np.full((round(height*.11),width,3),30,dtype=np.uint8)
                        y,thickness = round(height*.052),max(3,round(height*.005))
                        pixels[y:y+thickness,round(width*left):round(width*right)] = (218,75,58)
                        if white_track:
                            # Ordinary enemies may have a second short stagger bar.
                            lower=y+round(height*.019)
                            pixels[lower:lower+thickness,round(width*.43):round(width*.57)] = 215
                        self.assertFalse(boss_bar_present(Image.fromarray(pixels),(width,height)))

    def test_boss_rain_stops_after_eight_seconds_and_reappearance_resets_timer(self):
        gate = BossRainGate()
        self.assertTrue(gate.update(True,10))
        self.assertTrue(gate.update(False,17.99))
        self.assertFalse(gate.update(False,18))
        self.assertTrue(gate.update(True,20))
        self.assertTrue(gate.update(False,27))
        self.assertTrue(gate.update(True,27.5))
        self.assertTrue(gate.update(False,35.49))
        self.assertFalse(gate.update(False,35.5))

    def test_confirmed_boss_main_bar_keeps_rain_when_secondary_bar_is_hidden(self):
        with Image.open(Path(__file__).parent/'fixtures'/'boss-rain-top-bar.png') as source:
            strip=source.copy()
        width,height=2560,1440
        strip.paste((40,75,80),(round(width*.34),round(height*.065),
                                round(width*.67),round(height*.080)))
        self.assertFalse(boss_bar_present(strip,(width,height)))
        self.assertTrue(boss_bar_present(strip,(width,height),require_secondary=False))
        gate=BossRainGate()
        gate.update(True,0)
        for now in (5,10,20,40,80):
            seen=boss_bar_present(strip,(width,height),require_secondary=not gate.active)
            self.assertTrue(gate.update(seen,now))
        strip.paste((40,75,80),(round(width*.34),round(height*.047),
                                round(width*.67),round(height*.065)))
        self.assertFalse(boss_bar_present(strip,(width,height),require_secondary=False))
        self.assertTrue(gate.update(False,87.99))
        self.assertFalse(gate.update(False,88))

    def test_auto_gate_preserves_rain_during_ultimate_and_unknown_background(self):
        gate = BossRainGate()
        self.assertTrue(gate.update(True,0))
        self.assertTrue(gate.update(False,4))
        self.assertTrue(gate.update(None,100))
        self.assertFalse(gate.update(False,100))

    def test_passive_detector_never_restores_or_focuses_a_background_game(self):
        controller = Mock()
        controller.hwnd = 14
        user = Mock()
        user.IsIconic.return_value = False
        user.GetForegroundWindow.return_value = 20
        with patch.object(ctypes.windll, 'user32', user), patch('boss_rain.ImageGrab.grab') as grab:
            self.assertIsNone(passive_boss_sample(controller))
        grab.assert_not_called()
        user.ShowWindow.assert_not_called()
        user.SetForegroundWindow.assert_not_called()

    def test_fixed_mp3_repeat_command_and_stop_are_on_an_independent_alias(self):
        music = RainMusic()
        music._command = Mock(return_value='')
        music.start(app.RAIN_MUSIC_ASSET,30)
        self.assertTrue(music.playing)
        self.assertTrue(any(call.args[0] == f'play {music.alias} repeat' for call in music._command.call_args_list))
        music.stop()
        self.assertFalse(music.playing)
        music._command.assert_called_with(f'close {music.alias}')

    @unittest.skipUnless(os.name == 'nt','Windows layered surface')
    def test_native_layer_is_click_through_no_activate_and_releases_its_window(self):
        surface = LayeredRainSurface((-10000,-10000,160,120))
        hwnd = surface.hwnd
        try:
            user = surface.user
            user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user.GetWindowLongPtrW.argtypes = [ctypes.c_void_p,ctypes.c_int]
            self.assertEqual(user.GetWindowLongPtrW(hwnd,-20) & RAIN_WINDOW_STYLE, RAIN_WINDOW_STYLE)
            surface.present(premultiplied_bgra(RainScene(160,120,seed=5).frame(.05)))
            self.assertTrue(surface.visible)
            user.GetForegroundWindow.restype = ctypes.c_void_p
            self.assertNotEqual(user.GetForegroundWindow(),hwnd)
        finally:
            surface.close()
        surface.user.IsWindow.argtypes = [ctypes.c_void_p]
        self.assertFalse(surface.user.IsWindow(hwnd))


class Value:
    def __init__(self,value):
        self.value = value
    def get(self):
        return self.value
    def set(self,value):
        self.value = value


class RainControlTests(unittest.TestCase):
    def ui(self,mode):
        ui = app.App.__new__(app.App)
        ui.root = Mock()
        ui.rain_mode,ui.rain_level,ui.rain_strength,ui.rain_volume = Value(mode),Value('中雨'),Value('标准'),Value('30%')
        ui.rain_status,ui.window_title = Value(''),Value('自动')
        ui.rain_overlay = None
        ui.rain_music = Mock(playing=True)
        ui._boss_rain_watcher = None
        ui._boss_rain_active = False
        ui._rain_music_error = ''
        return ui

    def test_continuous_mode_ignores_running_tasks_and_off_stops_rain_and_music(self):
        ui = self.ui('持续下雨')
        ui.worker = Mock()
        ui.worker.is_alive.return_value = True
        with patch.object(app,'DesktopRain') as rain:
            ui._sync_rain()
            rain.assert_called_once()
            ui.rain_music.start.assert_called_once_with(app.RAIN_MUSIC_ASSET,30)
            ui.rain_mode.set('关闭')
            ui._sync_rain()
            rain.return_value.close.assert_called_once()
            ui.rain_music.stop.assert_called_once()

    def test_boss_mode_waits_for_bar_then_starts_fixed_music_and_rain(self):
        ui = self.ui('Boss战自动')
        with tempfile.TemporaryDirectory() as directory, patch.object(app,'RAIN_CONFIG',Path(directory)/'rain.json'), \
                patch.object(app,'BossRainWatcher') as watcher, patch.object(app,'DesktopRain') as rain:
            ui._apply_rain_settings()
            watcher.assert_called_once()
            rain.assert_not_called()
            ui.rain_music.start.assert_not_called()
            ui._on_boss_rain(True)
            rain.assert_called_once()
            ui.rain_music.start.assert_called_once_with(app.RAIN_MUSIC_ASSET,30)
            ui._on_boss_rain(False)
            rain.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
