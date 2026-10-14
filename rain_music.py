"""Loop the bundled Rain Love MP3 on its own Windows audio device alias."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import uuid


class RainMusic:
    def __init__(self):
        self.alias = 'wwbs_rain_'+uuid.uuid4().hex[:12]
        self.path = None
        self.playing = False
        self._api = None

    def _command(self, text):
        if self._api is None:
            self._api = ctypes.WinDLL('winmm', use_last_error=True)
            self._api.mciSendStringW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.HWND]
            self._api.mciSendStringW.restype = wintypes.DWORD
            self._api.mciGetErrorStringW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.UINT]
        result = ctypes.create_unicode_buffer(512)
        error = self._api.mciSendStringW(text, result, len(result), None)
        if error:
            explanation = ctypes.create_unicode_buffer(512)
            self._api.mciGetErrorStringW(error, explanation, len(explanation))
            raise OSError(explanation.value or f'MP3播放失败（{error}）')
        return result.value

    def start(self, path, volume=30):
        path = Path(path).resolve()
        if path.suffix.lower() != '.mp3' or not path.is_file():
            raise ValueError('内置《雨爱》音频文件缺失，请重新解压完整安装包。')
        if '"' in str(path):
            raise ValueError('MP3文件路径无效。')
        if self.playing and self.path == path:
            self.set_volume(volume)
            return
        self.stop()
        try:
            self._command(f'open "{path}" type mpegvideo alias {self.alias}')
            self.path = path
            self.set_volume(volume)
            self._command(f'play {self.alias} repeat')
            self.playing = True
        except Exception:
            self.stop()
            raise

    def set_volume(self, percent):
        if self.path is not None:
            self._command(f'setaudio {self.alias} volume to {max(0, min(100, int(percent)))*10}')

    def stop(self):
        if self.path is not None:
            try:
                self._command(f'close {self.alias}')
            except OSError:
                pass
            finally:
                self.path, self.playing = None, False
