"""Non-activating, click-through, per-pixel-alpha Windows desktop rain."""
import ctypes
from ctypes import wintypes
import os
import threading
import time

from rain_effect import RainScene, RAIN_STRENGTHS, premultiplied_bgra


RAIN_WINDOW_STYLE = 0x00080000 | 0x00000020 | 0x08000000 | 0x00000080 | 0x00000008


class BitmapHeader(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                ('image_size', wintypes.DWORD), ('xppm', wintypes.LONG), ('yppm', wintypes.LONG),
                ('used', wintypes.DWORD), ('important', wintypes.DWORD)]


class BitmapInfo(ctypes.Structure):
    _fields_ = [('header', BitmapHeader), ('colors', wintypes.DWORD*3)]


class Blend(ctypes.Structure):
    _fields_ = [('operation', ctypes.c_ubyte), ('flags', ctypes.c_ubyte),
                ('opacity', ctypes.c_ubyte), ('alpha_format', ctypes.c_ubyte)]


class Size(ctypes.Structure):
    _fields_ = [('width', wintypes.LONG), ('height', wintypes.LONG)]


def windows_api():
    if os.name != 'nt':
        raise OSError('桌面雨幕需要Windows系统。')
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    functions = (
        (user.CreateWindowExW, wintypes.HWND, [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]),
        (user.GetDC, wintypes.HDC, [wintypes.HWND]),
        (user.ReleaseDC, ctypes.c_int, [wintypes.HWND, wintypes.HDC]),
        (user.DestroyWindow, wintypes.BOOL, [wintypes.HWND]),
        (user.ShowWindow, wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
        (user.SetWindowDisplayAffinity, wintypes.BOOL, [wintypes.HWND, wintypes.DWORD]),
        (gdi.CreateCompatibleDC, wintypes.HDC, [wintypes.HDC]),
        (gdi.CreateDIBSection, wintypes.HBITMAP, [wintypes.HDC, ctypes.POINTER(BitmapInfo), wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]),
        (gdi.SelectObject, wintypes.HANDLE, [wintypes.HDC, wintypes.HANDLE]),
        (gdi.DeleteObject, wintypes.BOOL, [wintypes.HANDLE]),
        (gdi.DeleteDC, wintypes.BOOL, [wintypes.HDC]),
        (user.UpdateLayeredWindow, wintypes.BOOL, [wintypes.HWND, wintypes.HDC,
            ctypes.POINTER(wintypes.POINT), ctypes.POINTER(Size), wintypes.HDC,
            ctypes.POINTER(wintypes.POINT), wintypes.DWORD, ctypes.POINTER(Blend), wintypes.DWORD]),
    )
    for function, result, args in functions:
        function.restype, function.argtypes = result, args
    return user, gdi


def desktop_rectangle():
    user, _gdi = windows_api()
    return tuple(user.GetSystemMetrics(index) for index in (76, 77, 78, 79))


class LayeredRainSurface:
    def __init__(self, rectangle=None, *, exclude_capture=True):
        self.user, self.gdi = windows_api()
        self.rectangle = rectangle or desktop_rectangle()
        x, y, width, height = self.rectangle
        if min(width, height) < 1 or width*height > 32*1024*1024:
            raise ValueError('当前桌面尺寸超出雨幕支持范围。')
        self.hwnd = self.screen_dc = self.memory_dc = self.bitmap = self.original_bitmap = None
        self.bits = ctypes.c_void_p()
        self.visible = False
        self.capture_excluded = False
        try:
            self.hwnd = self.user.CreateWindowExW(RAIN_WINDOW_STYLE, 'STATIC', 'WWBS 桌面雨幕',
                0x80000000, x, y, width, height, None, None, None, None)
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self.screen_dc = self.user.GetDC(None)
            self.memory_dc = self.gdi.CreateCompatibleDC(self.screen_dc)
            info = BitmapInfo()
            info.header.size = ctypes.sizeof(BitmapHeader)
            info.header.width, info.header.height = width, -height
            info.header.planes, info.header.bits = 1, 32
            self.bitmap = self.gdi.CreateDIBSection(self.screen_dc, ctypes.byref(info), 0,
                                                   ctypes.byref(self.bits), None, 0)
            if not self.memory_dc or not self.bitmap or not self.bits.value:
                raise ctypes.WinError(ctypes.get_last_error())
            self.original_bitmap = self.gdi.SelectObject(self.memory_dc, self.bitmap)
            if exclude_capture:
                self.capture_excluded = bool(self.user.SetWindowDisplayAffinity(self.hwnd, 0x11))
        except Exception:
            self.close()
            raise

    def present(self, pixels: bytes, strength='标准'):
        if not self.hwnd:
            return
        x, y, width, height = self.rectangle
        if len(pixels) != width*height*4:
            raise ValueError('雨幕画面与桌面尺寸不一致')
        ctypes.memmove(self.bits, pixels, len(pixels))
        destination, origin = wintypes.POINT(x, y), wintypes.POINT(0, 0)
        size = Size(width, height)
        blend = Blend(0, 0, RAIN_STRENGTHS.get(strength, RAIN_STRENGTHS['标准']), 1)
        if not self.user.UpdateLayeredWindow(self.hwnd, self.screen_dc, ctypes.byref(destination),
                ctypes.byref(size), self.memory_dc, ctypes.byref(origin), 0, ctypes.byref(blend), 2):
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.visible:
            self.user.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE; never steal focus.
            self.visible = True

    def close(self):
        if self.hwnd:
            self.user.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.memory_dc and self.original_bitmap:
            self.gdi.SelectObject(self.memory_dc, self.original_bitmap)
        if self.bitmap:
            self.gdi.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.memory_dc:
            self.gdi.DeleteDC(self.memory_dc)
            self.memory_dc = None
        if self.screen_dc:
            self.user.ReleaseDC(None, self.screen_dc)
            self.screen_dc = None


class DesktopRain:
    def __init__(self, root, level='中雨', strength='标准', on_error=lambda error: None):
        self.root, self.level, self.strength, self.on_error = root, level, strength, on_error
        self.closed = False
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest = None
        self.surface = LayeredRainSurface()
        self._dimensions = self.surface.rectangle[2:]
        self._display_checked = time.monotonic()
        self._job = self.root.after(50, self._present)
        self.thread = threading.Thread(target=self._render, daemon=True, name='wwbs-rain-render')
        self.thread.start()

    def configure(self, level, strength):
        self.level, self.strength = level, strength

    def _render(self):
        try:
            scene, previous = None, time.monotonic()
            while not self._stop.is_set():
                start = time.monotonic()
                dimensions = self._dimensions
                if scene is None or (scene.width, scene.height) != dimensions:
                    scene = RainScene(*dimensions, self.level)
                scene.set_level(self.level)
                pixels = premultiplied_bgra(scene.frame(start-previous))
                previous = start
                if self._stop.is_set():
                    return
                with self._frame_lock:
                    self._latest = (dimensions, pixels)
                area = dimensions[0]*dimensions[1]
                interval = 1/(20 if area <= 4_000_000 else 12 if area <= 12_000_000 else 8)
                self._stop.wait(max(0, interval-(time.monotonic()-start)))
        except Exception as exc:
            with self._frame_lock:
                self._latest = exc

    def _present(self):
        self._job = None
        if self.closed:
            return
        try:
            if time.monotonic()-self._display_checked > 2:
                self._display_checked = time.monotonic()
                rectangle = desktop_rectangle()
                if rectangle != self.surface.rectangle:
                    replacement = LayeredRainSurface(rectangle)
                    self.surface.close()
                    self.surface = replacement
                    self._dimensions = rectangle[2:]
            with self._frame_lock:
                frame, self._latest = self._latest, None
            if isinstance(frame, Exception):
                raise frame
            if frame is not None and frame[0] == self._dimensions:
                self.surface.present(frame[1], self.strength)
        except Exception as exc:
            self.close()
            self.on_error(str(exc))
            return
        self._job = self.root.after(50, self._present)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._stop.set()
        if self._job:
            self.root.after_cancel(self._job)
            self._job = None
        self.surface.close()
