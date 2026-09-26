import threading
import unittest
from unittest.mock import Mock

from app import App


class StopHotkeyTests(unittest.TestCase):
    def test_async_key_polling_stops_once_per_key_press(self):
        application = App.__new__(App)
        application.root = Mock()
        application.root.winfo_exists.return_value = True
        application._hotkey_poll_job = None
        application._hotkey_ready = threading.Event()
        application._hotkey_status_reported = True
        application._hotkey_registered = False
        application._hotkey_triggered = threading.Event()
        application._hotkey_was_down = False
        application._stop_from_hotkey = Mock()
        application._stop_hotkey_is_down = Mock(side_effect=(True, True, False, True))

        for _ in range(4):
            application._poll_stop_hotkey()

        self.assertEqual(application._stop_from_hotkey.call_count, 2)
        self.assertEqual(application.root.after.call_count, 4)


if __name__ == "__main__":
    unittest.main()
