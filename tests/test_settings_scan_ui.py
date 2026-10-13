import threading
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import app


class SettingsScanUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry('900x720+100+50')
        self.ui = app.App.__new__(app.App)
        self.ui.root = self.root
        self.ui.worker = None
        self.ui.status = tk.StringVar(self.root)
        self.ui.local_settings_status = tk.StringVar(self.root)
        self.ui._offer_local_settings = Mock()
        self.exceptions = []
        self.root.report_callback_exception = lambda *args: self.exceptions.append(args)

    def tearDown(self):
        if getattr(self.ui, '_settings_scan_cancel', None):
            self.ui._settings_scan_cancel.set()
        self.root.destroy()

    def pump(self, milliseconds=250):
        self.root.after(milliseconds, self.root.quit)
        self.root.mainloop()
        self.assertEqual(self.exceptions, [])

    def test_result_before_mainloop_is_delivered_and_manual_click_shows_existing_scan(self):
        complete = threading.Event()
        def discover(*_args, **_options):
            complete.set()
            return None
        with patch.object(app, 'discover_latest', side_effect=discover):
            self.ui._detect_local_settings(automatic=True)
            self.assertTrue(complete.wait(1))
            self.ui._settings_scan_thread.join(timeout=1)
            self.assertFalse(self.ui._settings_scan_thread.is_alive())
            # User clicks while the automatic scan's result is still queued.
            self.ui._detect_local_settings()
            self.assertTrue(self.ui._settings_progress_window.winfo_exists())
            self.pump()
        self.ui._offer_local_settings.assert_called_once_with(None, False)
        self.assertFalse(self.ui._settings_scan_running)
        self.assertIsNone(self.ui._settings_progress_window)

    def test_cancel_allows_retry_and_late_old_result_cannot_replace_new_result(self):
        entered, release = threading.Event(), threading.Event()
        old, fresh = object(), object()
        def discover(*_args, **_options):
            if not entered.is_set():
                entered.set()
                release.wait(2)
                return old
            return fresh
        with patch.object(app, 'discover_latest', side_effect=discover), \
                patch.object(app, 'prepare_import', side_effect=lambda source, _target: source):
            try:
                self.ui._detect_local_settings()
                self.assertTrue(entered.wait(1))
                first_cancel = self.ui._settings_scan_cancel
                self.ui._cancel_settings_scan()
                self.assertTrue(first_cancel.is_set())
                self.assertFalse(self.ui._settings_scan_running)
                self.ui._detect_local_settings()
                release.set()
                self.pump()
            finally:
                release.set()
        self.ui._offer_local_settings.assert_called_once_with(fresh, False)
        self.assertFalse(self.ui._settings_scan_running)

    def test_error_is_reported_and_busy_flag_is_released_for_retry(self):
        with patch.object(app, 'discover_latest', side_effect=[OSError('fixture permission error'), None]), \
                patch.object(app.messagebox, 'showerror') as error:
            self.ui._detect_local_settings()
            self.pump()
            self.assertFalse(self.ui._settings_scan_running)
            error.assert_called_once()
            self.assertIn('fixture permission error', error.call_args.args[1])
            self.ui._detect_local_settings()
            self.pump()
        self.ui._offer_local_settings.assert_called_once_with(None, False)

    def test_auto_detection_waits_for_main_window_first_frame(self):
        self.ui._detect_local_settings = Mock()
        self.ui._startup_detect_local_settings()
        self.ui._detect_local_settings.assert_not_called()
        self.root._main_frame_ready = True
        with patch.object(app, 'discovery_needed', return_value=True):
            self.pump(350)
        self.ui._detect_local_settings.assert_called_once_with(automatic=True)


if __name__ == '__main__':
    unittest.main()
