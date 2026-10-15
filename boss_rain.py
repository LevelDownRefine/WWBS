"""Passive top-health-bar detector. Never focus, restore or operate the game."""
import ctypes
from ctypes import wintypes
import queue
import threading
import time

import numpy as np
from PIL import ImageGrab

from windows_client import ClientWindowController


def boss_bar_present(top_strip, game_size=None):
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
    luminance = region.mean(axis=2)
    distance = max(3, round(height*.006))
    # A bar has a thin horizontal edge against the scene, not a whole bright
    # sky band. Long names, small enemy bars and the player's bottom bar fail.
    for y in range(distance, region.shape[0]-distance):
        contrast = np.maximum(abs(luminance[y]-luminance[y-distance]),
                              abs(luminance[y]-luminance[y+distance])) > 18
        row = (health[y] | track[y]) & contrast
        positions = np.flatnonzero(row)
        if not len(positions):
            continue
        for group in np.split(positions, np.flatnonzero(np.diff(positions) > max(3, width*.003))+1):
            span = int(group[-1]-group[0]+1)
            if span >= width*.22 and len(group)/span > .75:
                return True
    return False


class BossRainGate:
    def __init__(self, grace=5.0):
        self.grace, self.active, self.last_seen = grace, False, float('-inf')

    def update(self, present, now):
        if present is None:
            return self.active  # Background/minimized game is unknown, not defeat.
        if present:
            self.active, self.last_seen = True, now
        elif now-self.last_seen >= self.grace:
            self.active = False
        return self.active


def passive_boss_sample(controller):
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
    return boss_bar_present(strip, size)


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
                present = passive_boss_sample(controller)
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
