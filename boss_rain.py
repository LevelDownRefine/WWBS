"""Passive top-health-bar detector. Never focus, restore or operate the game."""
import ctypes
from ctypes import wintypes
import queue
import threading
import time

import numpy as np
from PIL import ImageGrab

from windows_client import ClientWindowController


def boss_bar_present(top_strip, game_size=None, *, require_secondary=True):
    width, height = game_size or top_strip.size
    region = np.asarray(top_strip.convert('RGB'))
    region = region[round(height*.032):min(region.shape[0], round(height*.095)),
                    round(width*.22):round(width*.78)].astype(np.int16)
    if region.size == 0 or region.shape[0] < 7:
        return False
    red, green, blue = (region[:, :, index] for index in range(3))
    high, low = region.max(axis=2), region.min(axis=2)
    health = (red > 140) & (red > green*1.12) & (red > blue*1.22)
    track = (high > 105) & (high-low < 45)
    white = (low > 145) & (high-low < 45)
    luminance = region.mean(axis=2)
    distance = max(3, round(height*.006))
    bands = []
    # Boss HUD has two thin, centered tracks with aligned ends. A single long
    # enemy bar (even near the top), names and bright scenery are insufficient.
    for y in range(distance, region.shape[0]-distance):
        contrast = np.maximum(abs(luminance[y]-luminance[y-distance]),
                              abs(luminance[y]-luminance[y+distance])) > 18
        color_edge = np.maximum(abs(region[y]-region[y-distance]),
                                abs(region[y]-region[y+distance])).max(axis=1) > 45
        contrast |= color_edge
        row = (health[y] | track[y]) & contrast
        positions = np.flatnonzero(row)
        if not len(positions):
            continue
        for group in np.split(positions, np.flatnonzero(np.diff(positions) > max(3, width*.003))+1):
            left, right = int(group[0]), int(group[-1])
            span = right-left+1
            center = (left+right)/2+round(width*.22)
            if not width*.25 <= span <= width*.44 or len(group)/span < .85:
                continue
            if abs(center-width*.5) > width*.035:
                continue
            neutral = float(white[y, left:right+1].mean())
            if bands and y-bands[-1]['bottom'] <= 2:
                band = bands[-1]
                band['bottom'] = y
                band['rows'].append((left, right, neutral))
            else:
                bands.append({'top':y, 'bottom':y, 'rows':[(left,right,neutral)]})
    offset = round(height*.032)
    for main in bands:
        top, bottom = main['top']+offset, main['bottom']+offset
        if not height*.038 <= top <= height*.068:
            continue
        if not max(2, round(height*.001)) <= bottom-top+1 <= height*.015:
            continue
        if not require_secondary:
            return True  # Keep an already confirmed Boss session while its main bar remains.
        main_left, main_right, _ = np.median(main['rows'], axis=0)
        for lower in bands:
            gap = lower['top']-main['bottom']
            separation = lower['top']-main['top']
            if not height*.004 <= gap or not height*.010 <= separation <= height*.035:
                continue
            thickness = lower['bottom']-lower['top']+1
            if not max(2, round(height*.001)) <= thickness <= height*.012:
                continue
            lower_left, lower_right, neutral = np.median(lower['rows'], axis=0)
            if neutral < .80:
                continue
            if max(abs(main_left-lower_left), abs(main_right-lower_right)) <= width*.015:
                return True
    return False



class BossRainGate:
    def __init__(self, grace=8.0):
        self.grace, self.active, self.last_seen = grace, False, float('-inf')

    def update(self, present, now):
        if present is None:
            return self.active  # Background/minimized game is unknown, not defeat.
        if present:
            self.active, self.last_seen = True, now
        elif now-self.last_seen >= self.grace:
            self.active = False
        return self.active


def passive_boss_sample(controller, *, require_secondary=True):
    controller.connect()
    user = ctypes.windll.user32
    user.GetForegroundWindow.restype = wintypes.HWND
    user.IsIconic.argtypes = [wintypes.HWND]
    if user.IsIconic(controller.hwnd) or user.GetForegroundWindow() != controller.hwnd:
        return None
    left, top, right, bottom = controller._client_bbox()
    size = (right-left, bottom-top)
    # Only the game's top strip is read, in memory, with no screenshot files.
    strip = ImageGrab.grab(bbox=(left, top, right, top+round(size[1]*.11)),
                           include_layered_windows=False)
    return boss_bar_present(strip, size, require_secondary=require_secondary)


class BossRainWatcher:
    def __init__(self, root, title, on_changed):
        self.root, self.title, self.on_changed = root, title, on_changed
        self.stop = threading.Event()
        self.results = queue.Queue(maxsize=1)
        self.closed = False
        self._job = self.root.after(150, self._poll)
        self.thread = threading.Thread(target=self._work, daemon=True, name='wwbs-boss-rain')
        self.thread.start()

    def _work(self):
        gate, controller = BossRainGate(), None
        while not self.stop.is_set():
            try:
                if controller is None or controller.title_keyword != self.title:
                    controller = ClientWindowController(self.title)
                present = passive_boss_sample(controller, require_secondary=not gate.active)
            except Exception:
                present = None
            active = gate.update(present, time.monotonic())
            try:
                self.results.get_nowait()
            except queue.Empty:
                pass
            self.results.put_nowait(active)
            self.stop.wait(.25)

    def _poll(self):
        self._job = None
        if self.closed:
            return
        try:
            value = self.results.get_nowait()
        except queue.Empty:
            value = None
        if value is not None:
            self.on_changed(value)
        if not self.closed:
            self._job = self.root.after(150, self._poll)

    def close(self):
        self.closed = True
        self.stop.set()
        if self._job:
            self.root.after_cancel(self._job)
            self._job = None
