from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageChops, ImageGrab, ImageStat


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_RESTORE = 9
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_MOUSE = 0
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

DEFAULT_GAME_WINDOW_TITLES = ("鸣潮", "Wuthering Waves")
AUTO_TITLE_KEYWORDS = {"", "自动", "auto", "鸣潮", "wuthering waves"}
MIN_GAME_CLIENT_SIZE = (640, 360)


def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi_awareness()


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class ClientWindowController:
    def __init__(self, title_keyword: str = "自动", base_size: tuple[int, int] | None = None):
        self.title_keyword = title_keyword.strip() or "自动"
        self.title_keywords = self._expand_title_keywords(self.title_keyword)
        self.base_size = base_size
        self.hwnd = 0
        self.scale = 1.0
        self.last_capture_size: tuple[int, int] | None = None
        self.last_screen_bbox: tuple[int, int, int, int] | None = None
        self.last_capture_method = ""

    def connect(self) -> str:
        self.hwnd = self._find_window()
        title = self._window_title(self.hwnd)
        width, height = self.client_size()
        size_text = f"{width}x{height}"
        if self.base_size:
            base_width, base_height = self.base_size
            width_scale = width / base_width
            height_scale = height / base_height
            if abs(width_scale - height_scale) > 0.03:
                base = f"{base_width}x{base_height}"
                raise RuntimeError(f"已找到窗口：{title}，但当前 {size_text} 不是 {base} 的等比例缩放。")
            self.scale = (width_scale + height_scale) / 2
            base = f"{base_width}x{base_height}"
            return f"已找到窗口：{title}，当前 {size_text}，按 {base} 的 {self.scale:.3f} 倍识别"
        self.scale = 1.0
        return f"已找到窗口：{title}，分辨率 {size_text}"

    def template_scales(self) -> list[float]:
        return [self.scale, self.scale * 0.97, self.scale * 1.03, self.scale * 0.94, self.scale * 1.06]

    def screencap(self, target: Path, bring_to_front: bool = False) -> str:
        self._ensure_window()
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_RESTORE)
            time.sleep(0.18)
        bbox = self._client_bbox()
        self.last_screen_bbox = bbox

        # Pillow's window capture uses PrintWindow on Windows.  Unlike a desktop
        # crop it is not contaminated by wwbs (or any other window) covering the
        # game.  Some DirectX windows reject PrintWindow or return an empty frame,
        # so validate the result and fall back to a foreground desktop capture.
        image = None if self._requires_foreground_capture() else self._capture_window_client(bbox)
        method = "window"
        if (
            image is None
            or not self._capture_has_content(image)
            or self._capture_is_desktop_copy(image, bbox)
        ):
            image, bbox = self._capture_foreground_client()
            self.last_screen_bbox = bbox
            method = "foreground"

        expected_size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
        if image.size != expected_size:
            image = image.resize(expected_size, Image.Resampling.BILINEAR)
        self.last_capture_size = image.size
        self.last_capture_method = method
        image.save(target)
        return method

    def _requires_foreground_capture(self) -> bool:
        # Unreal/DirectX windows can make PrintWindow report success while it
        # returns a composed desktop (including wwbs) or an unrendered surface.
        # For these windows the dependable path is to focus the game first.
        return self._window_class_name() == "UnrealWindow"

    def _window_class_name(self) -> str:
        return self._window_class_name_for(self.hwnd)

    @staticmethod
    def _window_class_name_for(hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        if not user32.GetClassNameW(hwnd, buffer, len(buffer)):
            return ""
        return buffer.value

    def _capture_window_client(self, bbox: tuple[int, int, int, int]) -> Image.Image | None:
        try:
            window_image = ImageGrab.grab(window=self.hwnd).convert("RGB")
            client_width = bbox[2] - bbox[0]
            client_height = bbox[3] - bbox[1]
            if client_width <= 0 or client_height <= 0:
                return None

            # Current Pillow versions return the PrintWindow client image.  Its
            # pixel size can still be DPI-virtualized by the target process, so
            # normalize it to the physical client size used by our mapping.
            image_aspect = window_image.width / window_image.height
            client_aspect = client_width / client_height
            if abs(image_aspect / client_aspect - 1.0) <= 0.015:
                return window_image.resize((client_width, client_height), Image.Resampling.BILINEAR)

            # Keep compatibility with Pillow builds that return the full window.
            window_rect = RECT()
            if not user32.GetWindowRect(self.hwnd, ctypes.byref(window_rect)):
                return None
            client_left, client_top, client_right, client_bottom = bbox
            window_width = window_rect.right - window_rect.left
            window_height = window_rect.bottom - window_rect.top
            if window_width <= 0 or window_height <= 0:
                return None
            scale_x = window_image.width / window_width
            scale_y = window_image.height / window_height
            crop_box = (
                int(round((client_left - window_rect.left) * scale_x)),
                int(round((client_top - window_rect.top) * scale_y)),
                int(round((client_right - window_rect.left) * scale_x)),
                int(round((client_bottom - window_rect.top) * scale_y)),
            )
            if (
                crop_box[0] < 0
                or crop_box[1] < 0
                or crop_box[2] > window_image.width
                or crop_box[3] > window_image.height
            ):
                return None
            return window_image.crop(crop_box).resize((client_width, client_height), Image.Resampling.BILINEAR)
        except (OSError, TypeError, ValueError):
            return None

    def _capture_foreground_client(self) -> tuple[Image.Image, tuple[int, int, int, int]]:
        self._focus_window()
        if user32.GetForegroundWindow() != self.hwnd:
            # A second attempt helps when Windows' foreground-lock timeout races
            # with the worker thread that requested the capture.
            time.sleep(0.12)
            self._focus_window()
        for _attempt in range(4):
            time.sleep(0.35)
            bbox = self._client_bbox()
            image = ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
            if self._capture_has_content(image):
                return image, bbox
        raise RuntimeError("游戏窗口已置前，但连续获取到空白画面。请确认游戏未最小化后重试。")

    @staticmethod
    def _capture_has_content(image: Image.Image) -> bool:
        if image.width < 2 or image.height < 2:
            return False
        sample = image.convert("RGB")
        sample.thumbnail((160, 90), Image.Resampling.BILINEAR)
        extrema = sample.getextrema()
        dynamic_channels = sum(high - low >= 8 for low, high in extrema)
        deviation = sum(ImageStat.Stat(sample).stddev)
        return dynamic_channels >= 2 and deviation >= 6.0

    def _capture_is_desktop_copy(
        self,
        image: Image.Image,
        bbox: tuple[int, int, int, int],
    ) -> bool:
        try:
            desktop = ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
            if desktop.size != image.size:
                desktop = desktop.resize(image.size, Image.Resampling.BILINEAR)
            sample_size = (160, 90)
            first = image.resize(sample_size, Image.Resampling.BILINEAR)
            second = desktop.resize(sample_size, Image.Resampling.BILINEAR)
            mean_difference = sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / 3
            return mean_difference < 1.5
        except OSError:
            return False

    def tap(self, x: int, y: int) -> dict[str, tuple[int, int] | bool]:
        self._ensure_window()
        client_x, client_y = self.screenshot_to_client(x, y)
        screen_x, screen_y = self._screenshot_point_to_desktop(x, y)
        screen_x, screen_y = self._clamp_to_virtual_screen(screen_x, screen_y)
        before = self.cursor_position()
        self._focus_window()
        moved, input_x, input_y, move_method = self._set_cursor_with_dpi_fallback(screen_x, screen_y)
        time.sleep(0.08)
        after_move = self.cursor_position()
        self._send_mouse_button(MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.08)
        self._send_mouse_button(MOUSEEVENTF_LEFTUP)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        self._post_client_click(x, y)
        after_click = self.cursor_position()
        return {
            "target": (screen_x, screen_y),
            "input": (input_x, input_y),
            "method": move_method,
            "client": (client_x, client_y),
            "capture": self.last_capture_size or (-1, -1),
            "bbox": self.last_screen_bbox or (-1, -1, -1, -1),
            "before": before,
            "after_move": after_move,
            "after_click": after_click,
            "set_cursor_ok": moved,
        }

    def screenshot_to_client(self, x: int, y: int) -> tuple[int, int]:
        if not self.last_capture_size:
            return x, y
        capture_width, capture_height = self.last_capture_size
        client_width, client_height = self.client_size()
        if capture_width <= 0 or capture_height <= 0:
            return x, y
        mapped_x = int(round(x * client_width / capture_width))
        mapped_y = int(round(y * client_height / capture_height))
        return mapped_x, mapped_y

    def screenshot_to_screen(self, x: int, y: int) -> tuple[int, int]:
        if not self.last_capture_size or not self.last_screen_bbox:
            return self._client_to_screen(x, y)
        capture_width, capture_height = self.last_capture_size
        left, top, right, bottom = self.last_screen_bbox
        screen_width = right - left
        screen_height = bottom - top
        if capture_width <= 0 or capture_height <= 0:
            return self._client_to_screen(x, y)
        return (
            int(round(left + x * screen_width / capture_width)),
            int(round(top + y * screen_height / capture_height)),
        )

    def _screenshot_point_to_desktop(self, x: int, y: int) -> tuple[int, int]:
        if self.last_screen_bbox and self.last_capture_size:
            left, top, right, bottom = self.last_screen_bbox
            capture_width, capture_height = self.last_capture_size
            if capture_width > 0 and capture_height > 0:
                return (
                    int(round(left + x * (right - left) / capture_width)),
                    int(round(top + y * (bottom - top) / capture_height)),
                )
        if self.base_size:
            client_width, client_height = self.client_size()
            base_width, base_height = self.base_size
            return self._client_to_screen(
                int(round(x * client_width / base_width)),
                int(round(y * client_height / base_height)),
            )
        return self._client_to_screen(x, y)

    def swipe(self, x: int, y: int, x2: int, y2: int, duration_ms: int) -> None:
        self._ensure_window()
        sx, sy = self._client_to_screen(x, y)
        ex, ey = self._client_to_screen(x2, y2)
        user32.ShowWindow(self.hwnd, SW_RESTORE)
        user32.SetForegroundWindow(self.hwnd)
        user32.SetCursorPos(sx, sy)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        steps = max(4, int(duration_ms / 30))
        for index in range(1, steps + 1):
            t = index / steps
            user32.SetCursorPos(int(sx + (ex - sx) * t), int(sy + (ey - sy) * t))
            time.sleep(duration_ms / steps / 1000)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def text(self, value: str) -> None:
        raise RuntimeError("PC 客户端模式暂不支持自动输入文字。")

    def client_size(self) -> tuple[int, int]:
        self._ensure_window()
        rect = RECT()
        if not user32.GetClientRect(self.hwnd, ctypes.byref(rect)):
            raise RuntimeError("无法读取窗口分辨率。")
        return rect.right - rect.left, rect.bottom - rect.top

    def _ensure_window(self) -> None:
        if self.hwnd and user32.IsWindow(self.hwnd):
            return
        self.hwnd = self._find_window()

    def _find_window(self) -> int:
        candidates: list[tuple[int, str, int, int, str]] = []
        rejected_sizes: list[tuple[int, int]] = []
        current_pid = os.getpid()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == current_pid:
                    return True
                title = self._window_title(hwnd)
                if not title:
                    return True
                match_kind = self._title_match_kind(title, self.title_keywords)
                if match_kind == "none":
                    return True
                width, height = self._window_client_size(hwnd)
                if not self._is_plausible_game_size(width, height):
                    rejected_sizes.append((width, height))
                    return True
                class_name = self._window_class_name_for(hwnd)
                candidates.append((hwnd, match_kind, width, height, class_name))
            return True

        user32.EnumWindows(enum_proc, 0)
        if not candidates:
            attempted = "、".join(self.title_keywords)
            if rejected_sizes:
                sizes = "、".join(f"{width}x{height}" for width, height in sorted(set(rejected_sizes)))
                raise RuntimeError(
                    f"找到了同名小窗口（{sizes}），但它不是游戏画面。"
                    f"请确认国服或国际服 Steam 游戏已完成启动，而不是只打开启动器。"
                )
            raise RuntimeError(f"没有找到游戏窗口（已尝试：{attempted}）。请先打开国服或国际服 Steam PC 客户端。")
        candidates.sort(
            key=lambda candidate: self._candidate_sort_key(
                candidate[1], candidate[2], candidate[3], candidate[4]
            ),
            reverse=True,
        )
        return candidates[0][0]

    @staticmethod
    def _window_client_size(hwnd: int) -> tuple[int, int]:
        rect = RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return 0, 0
        return rect.right - rect.left, rect.bottom - rect.top

    @staticmethod
    def _is_plausible_game_size(width: int, height: int) -> bool:
        minimum_width, minimum_height = MIN_GAME_CLIENT_SIZE
        return width >= minimum_width and height >= minimum_height

    @staticmethod
    def _candidate_sort_key(match_kind: str, width: int, height: int, class_name: str) -> tuple[int, int, int]:
        return (
            1 if class_name == "UnrealWindow" else 0,
            1 if match_kind == "exact" else 0,
            width * height,
        )

    @staticmethod
    def _expand_title_keywords(value: str) -> tuple[str, ...]:
        normalized = value.strip()
        if normalized.casefold() in AUTO_TITLE_KEYWORDS:
            return DEFAULT_GAME_WINDOW_TITLES
        keywords = tuple(
            part.strip()
            for part in normalized.replace("，", ",").replace("；", ";").replace("/", "|").replace(",", "|").replace(";", "|").split("|")
            if part.strip()
        )
        return keywords or DEFAULT_GAME_WINDOW_TITLES

    @staticmethod
    def _title_match_kind(title: str, keywords: tuple[str, ...]) -> str:
        folded_title = title.strip().casefold()
        folded_keywords = tuple(keyword.strip().casefold() for keyword in keywords if keyword.strip())
        if folded_title in folded_keywords:
            return "exact"
        if any(keyword in folded_title for keyword in folded_keywords):
            return "partial"
        return "none"

    @staticmethod
    def _window_title(hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _client_bbox(self) -> tuple[int, int, int, int]:
        width, height = self.client_size()
        left_top = self._client_to_screen(0, 0)
        return (left_top[0], left_top[1], left_top[0] + width, left_top[1] + height)

    def _client_to_screen(self, x: int, y: int) -> tuple[int, int]:
        point = POINT(int(x), int(y))
        if not user32.ClientToScreen(self.hwnd, ctypes.byref(point)):
            raise RuntimeError("窗口坐标转换失败。")
        return point.x, point.y

    def _click_to_screen(self, x: int, y: int) -> tuple[int, int]:
        if self.last_capture_size and self.last_screen_bbox:
            return self.screenshot_to_screen(x, y)
        return self._client_to_screen(x, y)

    @staticmethod
    def _clamp_to_virtual_screen(x: int, y: int) -> tuple[int, int]:
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        width = user32.GetSystemMetrics(78)
        height = user32.GetSystemMetrics(79)
        if width <= 0 or height <= 0:
            return x, y
        return (
            max(left, min(x, left + width - 1)),
            max(top, min(y, top + height - 1)),
        )

    def _set_cursor_with_dpi_fallback(self, x: int, y: int) -> tuple[bool, int, int, str]:
        candidates = [(x, y)]
        scale = self._dpi_scale()
        if scale and abs(scale - 1.0) > 0.01:
            candidates.append((int(round(x / scale)), int(round(y / scale))))
        if self.last_screen_bbox:
            left, top, _right, _bottom = self.last_screen_bbox
            if scale and abs(scale - 1.0) > 0.01:
                candidates.append((int(round(left / scale + (x - left) / scale)), int(round(top / scale + (y - top) / scale))))

        seen: set[tuple[int, int]] = set()
        for candidate_x, candidate_y in candidates:
            point = (candidate_x, candidate_y)
            if point in seen:
                continue
            seen.add(point)
            if self._send_absolute_move(candidate_x, candidate_y):
                return True, candidate_x, candidate_y, "SendInputAbsolute"
            try:
                if user32.SetPhysicalCursorPos(candidate_x, candidate_y):
                    return True, candidate_x, candidate_y, "SetPhysicalCursorPos"
            except Exception:
                pass
            if user32.SetCursorPos(candidate_x, candidate_y):
                return True, candidate_x, candidate_y, "SetCursorPos"
        return False, x, y, "failed"

    def _send_absolute_move(self, x: int, y: int) -> bool:
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        width = user32.GetSystemMetrics(78)
        height = user32.GetSystemMetrics(79)
        if width <= 1 or height <= 1:
            return False
        absolute_x = int(round((x - left) * 65535 / (width - 1)))
        absolute_y = int(round((y - top) * 65535 / (height - 1)))
        move = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(
                mi=MOUSEINPUT(
                    absolute_x,
                    absolute_y,
                    0,
                    MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                    0,
                    0,
                )
            ),
        )
        sent = user32.SendInput(1, ctypes.byref(move), ctypes.sizeof(move))
        time.sleep(0.05)
        current = self.cursor_position()
        return sent == 1 and abs(current[0] - x) <= 2 and abs(current[1] - y) <= 2

    def _dpi_scale(self) -> float:
        try:
            dpi = user32.GetDpiForWindow(self.hwnd)
            if dpi:
                return dpi / 96.0
        except Exception:
            pass
        return 1.0

    @staticmethod
    def cursor_position() -> tuple[int, int]:
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return (-1, -1)
        return point.x, point.y

    def _focus_window(self) -> None:
        user32.ShowWindow(self.hwnd, SW_RESTORE)
        foreground = user32.GetForegroundWindow()
        current_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(self.hwnd, None)
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        if foreground_thread:
            user32.AttachThreadInput(current_thread, foreground_thread, True)
        if target_thread:
            user32.AttachThreadInput(current_thread, target_thread, True)
        try:
            user32.BringWindowToTop(self.hwnd)
            user32.SetActiveWindow(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.25)
        finally:
            if target_thread:
                user32.AttachThreadInput(current_thread, target_thread, False)
            if foreground_thread:
                user32.AttachThreadInput(current_thread, foreground_thread, False)

    @staticmethod
    def _send_mouse_button(flag: int) -> None:
        event = INPUT(type=INPUT_MOUSE, union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, flag, 0, 0)))
        sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
        if sent != 1:
            raise RuntimeError("鼠标点击发送失败。")

    def _post_client_click(self, x: int, y: int) -> None:
        lparam = (int(y) << 16) | (int(x) & 0xFFFF)
        user32.PostMessageW(self.hwnd, WM_LBUTTONDOWN, 1, lparam)
        user32.PostMessageW(self.hwnd, WM_LBUTTONUP, 0, lparam)
