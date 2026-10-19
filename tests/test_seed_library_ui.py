import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import app


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


class SeedLibraryUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry('900x700')
        self.ui = app.App.__new__(app.App)
        self.ui.root = self.root

    def tearDown(self):
        self.root.destroy()

    def wait_job(self, dialog):
        deadline = time.monotonic()+3
        self.root.update()
        while getattr(dialog, '_seed_job_running', False) and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(getattr(dialog, '_seed_job_running', False))

    def test_open_loads_recent_records_without_search_and_selects_first(self):
        workers = []
        def search(query):
            workers.append(threading.get_ident())
            self.assertEqual(query, '')
            return ([{'id': 'a'*24, 'name': '最新上传', 'modules': 18},
                     {'id': 'b'*24, 'name': '之前上传', 'modules': 15}], False)
        with patch.object(app, 'search_seeds', side_effect=search) as request:
            dialog = self.ui._rotation_online_seed_library()
            self.wait_job(dialog)
        request.assert_called_once_with('')
        self.assertNotEqual(workers[0], threading.get_ident())
        text = next(w for w in walk(dialog) if isinstance(w, tk.Text))
        self.assertTrue(text.get('1.0', 'end').startswith('最新上传'))
        self.assertEqual(str(text.tag_ranges('selected')[0]), '1.0')

    def test_network_error_is_visible_and_does_not_leave_a_blank_silent_dialog(self):
        with patch.object(app, 'search_seeds', side_effect=RuntimeError('连接失败，请检查网络')):
            dialog = self.ui._rotation_online_seed_library()
            self.wait_job(dialog)
        values = [self.root.getvar(w.cget('textvariable')) for w in walk(dialog)
                  if isinstance(w, tk.Label) and w.cget('textvariable')]
        self.assertIn('连接失败，请检查网络', values)
