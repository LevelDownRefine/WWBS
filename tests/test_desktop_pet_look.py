import inspect
import unittest
from unittest.mock import Mock

from PIL import Image

from desktop_pet import DesktopPet
import jingran_persona


class DesktopPetLookTests(unittest.TestCase):
    def test_hidden_pet_feedback_changes_state_without_showing_window(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.frames = {"idle": [object()], "running": [object()]}
        pet.visible = False
        pet.state = "idle"
        pet.frame_index = 0
        pet.state_cycles = 0
        pet.show = Mock()

        pet.play("running")
        pet.say("任务开始")

        self.assertEqual(pet.state, "running")
        pet.show.assert_not_called()

    def test_look_frames_are_loaded_before_animation_starts(self) -> None:
        source = inspect.getsource(DesktopPet.__init__)
        self.assertLess(source.index("self.look_frames ="), source.index("self._animate()"))

    def test_sixteen_direction_mapping_starts_up_and_runs_clockwise(self) -> None:
        self.assertEqual(DesktopPet._look_direction_index(0, -100), 0)
        self.assertEqual(DesktopPet._look_direction_index(100, 0), 4)
        self.assertEqual(DesktopPet._look_direction_index(0, 100), 8)
        self.assertEqual(DesktopPet._look_direction_index(-100, 0), 12)

    def test_pointer_deadzone_uses_normal_idle_animation(self) -> None:
        self.assertIsNone(DesktopPet._look_direction_index(3, 4, deadzone=5))

    def test_name_badge_expands_for_cartethyia(self) -> None:
        self.assertGreater(
            DesktopPet._name_badge_width("卡提希娅"),
            DesktopPet._name_badge_width("爱弥斯"),
        )

    def test_pointer_look_can_be_disabled(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.look_enabled = False
        pet.look_frames = [object()]
        pet.state = "idle"
        pet.dragging = False
        pet.working = False

        self.assertIsNone(pet._pointer_look_frame())

    def test_enabled_auto_jump_plays_and_reschedules(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.auto_jump_enabled = True
        pet.visible = True
        pet.working = False
        pet.state = "idle"
        pet.dragging = False
        pet._bubble_job = None
        pet._auto_jump_job = object()
        pet.window = Mock()
        pet.play = Mock()

        pet._auto_jump_tick()

        pet.play.assert_called_once_with("jumping")
        pet.window.after.assert_called_once()

    def test_disabled_auto_jump_cancels_scheduled_job(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.auto_jump_enabled = True
        pet._auto_jump_job = "job-id"
        pet.window = Mock()

        pet.set_auto_jump_enabled(False)

        pet.window.after_cancel.assert_called_once_with("job-id")
        self.assertIsNone(pet._auto_jump_job)

    def test_right_click_look_toggle_notifies_app(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.look_enabled_var = Mock()
        pet.look_enabled_var.get.return_value = False
        pet.on_look_enabled_changed = Mock()

        pet._toggle_look_from_menu()

        self.assertFalse(pet.look_enabled)
        pet.on_look_enabled_changed.assert_called_once_with(False)

    def test_right_click_auto_jump_toggle_notifies_app(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.auto_jump_enabled_var = Mock()
        pet.auto_jump_enabled_var.get.return_value = True
        pet.on_auto_jump_enabled_changed = Mock()
        pet.set_auto_jump_enabled = Mock()
        pet.auto_jump_enabled = True

        pet._toggle_auto_jump_from_menu()

        pet.set_auto_jump_enabled.assert_called_once_with(True)
        pet.on_auto_jump_enabled_changed.assert_called_once_with(True)

    def test_optional_alpha_cutoff_removes_partial_tk_edges(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.alpha_cutoff = 128
        source = Image.new("RGBA", (3, 1))
        source.putdata(((10, 20, 30, 0), (40, 50, 60, 128), (70, 80, 90, 129)))

        prepared = pet._prepare_image(source)

        self.assertEqual(list(prepared.getchannel("A").tobytes()), [0, 0, 255])

    def test_scaled_frames_are_hardened_after_resampling(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.alpha_cutoff = 128
        source = Image.new("RGBA", (2, 1))
        source.putdata(((255, 255, 255, 0), (255, 255, 255, 255)))

        prepared = pet._scale_and_prepare_image(source, (7, 3))

        self.assertEqual(set(prepared.getchannel("A").tobytes()), {0, 255})

    def test_landing_pose_is_smaller_and_stays_grounded(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.alpha_cutoff = None
        source = Image.new("RGBA", (100, 100), (255, 255, 255, 255))

        landing = pet._scale_and_prepare_landing_image(source, (100, 100))
        alpha_box = landing.getchannel("A").getbbox()

        self.assertEqual(alpha_box, (3, 6, 97, 100))
        self.assertEqual(DesktopPet.STATE_DELAYS["landing"], 150)
        self.assertEqual(DesktopPet.ONE_SHOT_REPEATS["landing"], 4)

    def test_forward_jump_starts_in_current_facing_direction(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.visible = True
        pet.working = False
        pet.dragging = False
        pet.state = "idle"
        pet._jump_motion_job = None
        pet._facing_direction = -1
        pet._airborne = False
        pet.width = 192
        pet.frame_index = 0
        pet.state_cycles = 0
        pet.root = Mock()
        pet.root.winfo_screenwidth.return_value = 1920
        pet.window = Mock()
        pet.window.winfo_x.return_value = 900
        pet.window.winfo_y.return_value = 500
        pet._cancel_roam = Mock()
        pet._cancel_move = Mock()
        pet._show_airborne_pose = Mock()
        pet._jump_motion_tick = Mock()

        self.assertTrue(pet._begin_forward_jump())
        self.assertTrue(pet._airborne)
        self.assertEqual(pet.state, "jumping")
        self.assertEqual(pet._facing_direction, -1)
        pet._show_airborne_pose.assert_called_once_with()
        pet._jump_motion_tick.assert_called_once_with()

    def test_forward_jump_finishes_with_landing_action(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet._jump_motion_job = object()
        pet._airborne = True
        pet.frames = {"landing": [object()]}
        pet.window = Mock()
        pet.roaming = False
        pet.working = False
        pet.frame_index = 4
        pet.state_cycles = 2

        pet._finish_forward_jump(420, 360)

        pet.window.geometry.assert_called_once_with("+420+360")
        self.assertFalse(pet._airborne)
        self.assertEqual(pet.state, "landing")
        self.assertEqual(pet.frame_index, 0)

    def test_jingran_chatter_selects_a_one_shot_action(self) -> None:
        jingran_persona._idle_action_bag.clear()
        dialogue = jingran_persona.idle_line()
        self.assertTrue(
            dialogue.text in jingran_persona.IDLE_LINES
            or dialogue.text.removeprefix("漂泊者，") in jingran_persona.IDLE_LINES
        )
        self.assertIn(dialogue.action, DesktopPet.CHATTER_ACTIONS)

    def test_jingran_double_click_speaks_immediately(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.speak_on_interact = True
        pet.forward_jump_enabled = True
        pet._speak_generated_line = Mock()
        pet._schedule_chatter = Mock()
        pet.play = Mock()

        pet._interact()

        pet._speak_generated_line.assert_called_once_with(play_action=False)
        pet._schedule_chatter.assert_called_once_with()
        pet.play.assert_called_once_with("jumping")

    def test_other_pet_double_click_keeps_action_only_behavior(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.speak_on_interact = False
        pet.forward_jump_enabled = False
        pet.play = Mock()

        pet._interact()

        pet.play.assert_called_once()
        self.assertIn(pet.play.call_args.args[0], ("waving", "jumping", "review"))

    def test_cartethyia_double_click_always_uses_forward_jump(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.speak_on_interact = False
        pet.forward_jump_enabled = True
        pet.play = Mock()

        pet._interact()

        pet.play.assert_called_once_with("jumping")

    def test_airborne_animation_holds_middle_jump_pose(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        jump_frames = [object() for _ in range(5)]
        pet.visible = True
        pet.frames = {"jumping": jump_frames}
        pet.state = "jumping"
        pet._airborne = True
        pet.frame_index = 0
        pet.state_cycles = 0
        pet.dragging = False
        pet.canvas = Mock()
        pet.image_item = object()
        pet._pointer_look_frame = Mock(return_value=None)
        pet.window = Mock()
        pet.window.after = Mock(return_value=object())

        pet._animate()

        self.assertIs(pet.canvas.itemconfigure.call_args.kwargs["image"], jump_frames[2])
        self.assertEqual(pet.frame_index, 0)

    def test_jingran_jump_appears_in_every_random_action_round(self) -> None:
        jingran_persona._idle_action_bag.clear()
        actions = {jingran_persona.idle_line().action for _ in jingran_persona.IDLE_ACTIONS}
        self.assertEqual(actions, set(jingran_persona.IDLE_ACTIONS))


if __name__ == "__main__":
    unittest.main()
