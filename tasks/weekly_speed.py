"""One reminder when the first visible weekly speed control is below MAX."""
import re
import unicodedata

import numpy as np
from PIL import Image

from image_matcher import MatchResult
from windows_ocr import WindowsOcr


def speed_text(lines, region):
    left, top, right, bottom = region
    words = [word for line in lines for word in line.get('words', [])
             if left <= word['x']+word['width']/2 < right
             and top <= word['y']+word['height']/2 < bottom]
    text = ''.join(str(word.get('text', '')) for word in sorted(words, key=lambda word: word['x']))
    text = unicodedata.normalize('NFKC', text).upper().replace('×', 'X')
    text = re.sub(r'[^A-Z0-9.]', '', text)
    if text == 'MAX':
        return 'MAX'
    match = re.fullmatch(r'X(\d{1,2}(?:\.\d{1,2})?)|(\d{1,2}(?:\.\d{1,2})?)X|(\d{1,2}\.\d{1,2})', text)
    if match:
        number = float(next(group for group in match.groups() if group is not None))
        if 0 < number <= 99:
            return f'×{number:g}'
    return None


class WeeklySpeedReminder:
    def __init__(self, *, ocr_factory=WindowsOcr):
        self.ocr_factory = ocr_factory
        self.finished = False
        self.previous = None

    def observe(self, screenshot, vision, runner):
        if self.finished or runner.stop_event.is_set():
            return
        anchor = getattr(vision, '_day_anchor', None)
        if not isinstance(anchor, MatchResult):
            return  # Hidden toolbar / loading is not proof of a wrong speed.
        scale = anchor.width/52
        with Image.open(screenshot) as image:
            region = (max(0, round(anchor.x+375*scale)), max(0, round(anchor.y-15*scale)),
                      min(image.width, round(anchor.x+535*scale)), min(image.height, round(anchor.y+45*scale)))
            if region[2]-region[0] < 30*scale or region[3] <= region[1]:
                return
            pixels = np.asarray(image.crop(region).convert('L').resize((96, 32)), dtype=np.int16)
        try:
            vision.matcher.find_fast(screenshot, 'weekly/speed_max.png', .9, scale,
                                     region=region, max_width=600)
        except (OSError, RuntimeError):
            pass
        else:
            self.finished = True
            return
        previous = self.previous
        self.previous = (region, pixels)
        if previous is None or previous[0] != region or float(np.abs(pixels-previous[1]).mean()) > 8:
            return
        # Use optional local OCR only once, after two fresh stable toolbar views.
        # No new OCR dependency is imposed on the rest of the weekly task.
        worker = None
        try:
            worker = self.ocr_factory()
            lines = worker.recognize(screenshot, cancelled=runner.stop_event.is_set, timeout=2.5)
            speed = speed_text(lines, region)
        except InterruptedError:
            return
        except (OSError, RuntimeError):
            speed = None
        finally:
            if worker is not None:
                worker.close()
        self.finished = True
        if runner.stop_event.is_set() or speed == 'MAX':
            return
        if speed:
            message = f'周常当前倍速为{speed}，尚未设为MAX，请手动把右上角倍速改成MAX。'
        else:
            message = '暂时无法确认周常倍速，请手动检查右上角是否为MAX；程序不会替你切换倍速。'
        runner.log('    倍速提醒：'+message)
        runner.warning(message)
