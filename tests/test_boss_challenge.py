import unittest
from unittest.mock import Mock, patch

import app
import combat_4c_entrance
from combat_4c_entrance import LEVEL_ROWS, BossChallengeEntrance


class BossChallengeTests(unittest.TestCase):
    def make_runner(self):
        runner = app.TaskRunner(
            Mock(), Mock(), dry_run=False,
            boss_challenge=BossChallengeEntrance(enabled=True, level="90"),
        )
        runner._sleep_interruptible = Mock()
        runner._tap_ratio = Mock()
        entry = runner.boss_challenge
        entry.entry_row_ratio = Mock(return_value=0.6)
        entry.wait_for_battle = Mock(return_value=True)
        runner._run_4c_battle = Mock()
        runner._collect_4c_reward = Mock()
        return runner, entry

    def test_entry_confirms_battle_before_attacking(self):
        runner, entry = self.make_runner()
        entry.entry_row_ratio.side_effect = [None, 0.6]
        events = Mock()
        events.attach_mock(entry.wait_for_battle, "ready")
        events.attach_mock(runner._run_4c_battle, "battle")
        runner._run_4c_combat(Mock())
        self.assertEqual([event[0] for event in events.mock_calls], ["ready", "battle"])
        runner.controller.press_key.assert_called_once_with("F2", 100)
        runner._tap_ratio.assert_any_call(entry.BOSS_CHALLENGE_X, 0.6, 2.0)
        runner._tap_ratio.assert_any_call(entry.BOSS_CHALLENGE_LEVEL_X, LEVEL_ROWS["90"], 0.5)

    def test_failed_or_cancelled_entry_does_not_attack(self):
        for outcome in ("missing-row", "timeout", "cancelled"):
            with self.subTest(outcome=outcome):
                runner, entry = self.make_runner()
                entry.wait_for_battle.return_value = False
                if outcome == "missing-row":
                    entry.BOSS_ENTRY_TIMEOUT = 0
                if outcome == "cancelled":
                    entry.wait_for_battle.side_effect = lambda *_args: runner.stop_event.set() or False
                    runner._run_4c_combat(Mock())
                else:
                    with self.assertRaisesRegex(RuntimeError, "已停止4C"):
                        runner._run_4c_combat(Mock())
                runner._run_4c_battle.assert_not_called()
                runner._collect_4c_reward.assert_not_called()
                runner.controller.release_keys.assert_called_once()

    def test_disabled_entry_and_dry_run_send_no_entry_input(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                runner, entry = self.make_runner()
                runner.dry_run = dry_run
                if not dry_run:
                    runner.boss_challenge = BossChallengeEntrance()
                runner._run_4c_combat(Mock())
                runner.controller.press_key.assert_not_called()
                runner._tap_ratio.assert_not_called()
                entry.wait_for_battle.assert_not_called()

    def test_loading_requires_consecutive_headers_and_can_time_out(self):
        for headers, ready in (([True, False, True, True], True), ([True, False, False, False], False)):
            with self.subTest(headers=headers):
                runner = app.TaskRunner(Mock(), Mock(), boss_challenge=BossChallengeEntrance())
                entry = runner.boss_challenge
                now = 0.0
                def tick(delay):
                    nonlocal now
                    now += delay
                with (
                    patch.object(combat_4c_entrance.time, "monotonic", side_effect=lambda: now),
                    patch.object(runner, "_inspect_4c_boss_header", side_effect=headers) as inspect,
                    patch.object(runner, "_sleep_interruptible", side_effect=tick),
                ):
                    self.assertEqual(entry.wait_for_battle(runner, timeout=2), ready)
                self.assertEqual(inspect.call_count, 4)
