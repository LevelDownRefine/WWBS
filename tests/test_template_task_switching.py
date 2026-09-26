import unittest
from unittest.mock import Mock

import app


def task(name: str, group: str, enabled: bool, action: str) -> app.WeeklyTask:
    return app.WeeklyTask(
        name=name,
        enabled=enabled,
        template_group=group,
        steps=[app.Step(action=action)],
    )


class TemplateTaskSwitchingTests(unittest.TestCase):
    def setUp(self):
        self.dream = task("幻梦游园", "default", False, "tap_image_cycle")
        self.chorus = task("群声共振模拟域", "群声共振模拟域", True, "move_to_visual_target")
        self.combat = task("4C刷取", "4c", False, "combat_4c")
        self.tasks = [self.dream, self.chorus, self.combat]

    def test_switching_to_default_disables_chorus(self):
        active = app.App._activate_template_group_task(self.tasks, "幻梦游园")
        self.assertIs(active, self.dream)
        self.assertTrue(self.dream.enabled)
        self.assertFalse(self.chorus.enabled)
        self.assertFalse(self.combat.enabled)

    def test_switching_to_chorus_disables_default(self):
        self.dream.enabled = True
        self.chorus.enabled = False
        active = app.App._activate_template_group_task(self.tasks, "群声共振模拟域")
        self.assertIs(active, self.chorus)
        self.assertFalse(self.dream.enabled)
        self.assertTrue(self.chorus.enabled)

    def test_4c_group_does_not_replace_normal_task(self):
        active = app.App._activate_template_group_task(self.tasks, "4c")
        self.assertIsNone(active)
        self.assertTrue(self.chorus.enabled)
        self.assertFalse(self.combat.enabled)

    def test_packaged_default_template_is_dream_park(self):
        tasks = app.ConfigStore(app.DEFAULT_CONFIG).load()
        enabled = [item for item in tasks if item.enabled]
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].name, "幻梦游园")
        self.assertEqual(enabled[0].template_group, "default")

    def test_4c_launcher_forces_packaged_group_without_changing_selection(self):
        launcher = app.App.__new__(app.App)
        misconfigured = task("4C刷取", "default", False, "combat_4c")
        launcher.tasks = [misconfigured]
        launcher.target_mode = Mock()
        launcher.target_mode.get.return_value = "client"
        launcher.max_cycles = None
        launcher.dry_run = Mock()
        launcher._start_worker = Mock()

        launcher._start_named_task_real("4C刷取", 5, require_confirmation=False)

        launched = launcher._start_worker.call_args.args[0][0]
        self.assertEqual(launched.template_group, "4c")
        self.assertTrue(launched.enabled)
        self.assertEqual(misconfigured.template_group, "default")
        self.assertEqual(launcher.max_cycles, 5)


if __name__ == "__main__":
    unittest.main()
