from __future__ import annotations

import queue
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import App
import app as app_module


class RuntimeDiagnosisTests(unittest.TestCase):
    @staticmethod
    def _app(tasks, due=True):
        app = App.__new__(App)
        app.tasks = tasks
        app._is_due = Mock(return_value=due)
        app._log = Mock()
        app._diagnose_runtime = Mock()
        app._start_worker = Mock()
        app._event_line = Mock(return_value="已找到具体原因")
        app._pet_feedback = Mock()
        return app

    def test_no_enabled_task_starts_diagnosis_directly(self) -> None:
        app = self._app([SimpleNamespace(enabled=False)])
        app._run_enabled()
        app._diagnose_runtime.assert_called_once_with()
        app._start_worker.assert_not_called()

    def test_no_due_task_starts_diagnosis_directly(self) -> None:
        app = self._app([SimpleNamespace(enabled=True)], due=False)
        app._run_enabled()
        app._diagnose_runtime.assert_called_once_with()
        app._start_worker.assert_not_called()

    def test_eligible_task_starts_worker(self) -> None:
        task = SimpleNamespace(enabled=True)
        app = self._app([task], due=True)
        app._run_enabled()
        app._start_worker.assert_called_once_with([task])
        app._diagnose_runtime.assert_not_called()

    def test_task_failure_reports_known_reason_then_runs_silent_diagnosis(self) -> None:
        app = self._app([])
        app._show_task_error_feedback("未找到模板")
        app._diagnose_runtime.assert_called_once_with(announce=False)
        app._event_line.assert_called_once()
        self.assertEqual(app._event_line.call_args.args[0], "diagnose_error")
        app._pet_feedback.assert_called_once()

    def test_log_reader_notifies_pet_about_mouse_move_failure(self) -> None:
        app = App.__new__(App)
        app.log_queue = queue.Queue()
        app.log_queue.put("[17:21:53] 鼠标没有移动成功：请尝试右键桌面快捷方式，以管理员身份运行。")
        app.detail = Mock()
        app.status = Mock()
        app.root = Mock()
        app._notify_mouse_move_failure = Mock()
        app._drain_logs()
        app._notify_mouse_move_failure.assert_called_once_with()

    def test_mouse_move_warning_has_cooldown(self) -> None:
        app = App.__new__(App)
        app._last_mouse_admin_warning_at = 0.0
        app._event_line = Mock(return_value="请以管理员身份运行")
        app._pet_feedback = Mock()
        with patch.object(app_module.time, "monotonic", side_effect=(100.0, 105.0, 113.0)):
            app._notify_mouse_move_failure()
            app._notify_mouse_move_failure()
            app._notify_mouse_move_failure()
        self.assertEqual(app._pet_feedback.call_count, 2)

    @staticmethod
    def _preflight_app() -> App:
        app = App.__new__(App)
        app._preflight_running = False
        app.target_mode = Mock()
        app.target_mode.get.return_value = "client"
        app.tasks = [SimpleNamespace(enabled=True)]
        app._is_due = Mock(return_value=True)
        app._pet_feedback = Mock()
        app._event_line = Mock(return_value="正在检查")
        app.window_title = Mock()
        app.window_title.get.return_value = "鸣潮"
        app._parse_resolution = Mock(return_value=(1920, 1080))
        app.template_group = Mock()
        app.template_group.get.return_value = "default"
        app._template_group_dir = Mock(return_value=Path("templates"))
        app._run_enabled = Mock()
        app._show_task_error_feedback = Mock()
        app._log = Mock()
        app.root = Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        return app

    def test_fast_preflight_starts_task_after_success(self) -> None:
        app = self._preflight_app()
        controller = Mock()
        controller.scale = 1.0
        immediate_thread = lambda target, daemon: SimpleNamespace(start=target)
        with (
            patch.object(app_module, "ClientWindowController", return_value=controller),
            patch.object(app_module, "TemplateMatcher"),
            patch.object(app_module.threading, "Thread", side_effect=immediate_thread),
        ):
            app._preflight_enabled_run()
        app._run_enabled.assert_called_once_with()
        app._show_task_error_feedback.assert_not_called()
        self.assertFalse(app._preflight_running)

    def test_fast_preflight_reports_failure_before_worker(self) -> None:
        app = self._preflight_app()
        controller = Mock()
        controller.connect.side_effect = RuntimeError("没有找到游戏窗口")
        immediate_thread = lambda target, daemon: SimpleNamespace(start=target)
        with (
            patch.object(app_module, "ClientWindowController", return_value=controller),
            patch.object(app_module.threading, "Thread", side_effect=immediate_thread),
        ):
            app._preflight_enabled_run()
        app._show_task_error_feedback.assert_called_once_with("没有找到游戏窗口")
        app._run_enabled.assert_not_called()
        self.assertFalse(app._preflight_running)


if __name__ == "__main__":
    unittest.main()
