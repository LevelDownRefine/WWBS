from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

import cartethyia_persona as persona


class CartethyiaPersonaTests(unittest.TestCase):
    def test_prompt_layers_anchor_normal_cartethyia(self) -> None:
        combined = "\n".join(
            (
                persona.SYSTEM_PROMPT,
                persona.CHARACTER_PROMPT,
                persona.PERSONALITY_PROMPT,
                persona.DIALOGUE_PROMPT,
            )
        )
        self.assertIn("流浪骑士", combined)
        self.assertIn("义人", combined)
        self.assertIn("芙露德莉斯", combined)
        self.assertIn("不是主人", combined)

    def test_signature_line_is_preserved(self) -> None:
        self.assertEqual(persona.SIGNATURE_LINE, "即便身处命运的漩涡，我也有想要坚持的事。")
        self.assertIn(persona.SIGNATURE_LINE, persona.IDLE_LINES)

    def test_required_events_render(self) -> None:
        required = {
            "task_start", "task_complete", "check_start", "check_success",
            "check_failure", "diagnose_start", "diagnose_error",
            "diagnose_warning", "diagnose_ok", "stop_requested",
            "mouse_move_failed",
        }
        self.assertTrue(required.issubset(persona.EVENT_LINES))
        for event in required:
            values = {"detail": "测试原因"} if event in {"diagnose_error", "diagnose_warning"} else {}
            self.assertTrue(persona.event_line(event, **values).strip())

    def test_every_idle_action_appears_once_per_round(self) -> None:
        persona._idle_action_bag.clear()
        actions = {persona.idle_line().action for _ in persona.IDLE_ACTIONS}
        self.assertEqual(actions, set(persona.IDLE_ACTIONS))

    def test_default_dialogue_never_uses_fleurdelis_mode(self) -> None:
        engine = persona.DialogueEngine()
        samples = [engine.proactive() for _ in range(100)]
        self.assertTrue(
            all(line.mode is persona.PersonaMode.CARDI_NORMAL for line in samples)
        )

    def test_special_address_tiers(self) -> None:
        self.assertEqual(persona.address_for("direct_call"), "义人")
        self.assertEqual(persona.address_for("serious"), "漂泊者")
        self.assertEqual(persona.address_for("quest"), "持剑之人")
        self.assertEqual(persona.address_for("festival"), "摘桂之人")
        self.assertEqual(persona.address_for("fleur"), "弑神者")
        self.assertEqual(persona.address_for("birthday", "小明"), "小明")

    def test_requested_user_messages_generate_in_character_replies(self) -> None:
        engine = persona.DialogueEngine()
        messages = (
            "我回来了。",
            "我要出去一趟。",
            "你想我了吗？",
            "我想你了。",
            "今天累死了。",
            "我失败了。",
            "我自己扛就行。",
            "如果牺牲我一个就能解决呢？",
            "卡提希娅，救救我。",
            "圣女大人。",
            "芙露德莉斯。",
            "你保护得了我吗？",
            "我要睡觉了。",
            "我三天没打开你。",
            "任务终于做完了。",
            "你好漂亮。",
            "我喜欢你。",
        )
        replies = {message: engine.respond(message) for message in messages}
        self.assertTrue(all(reply.text.strip() for reply in replies.values()))
        self.assertTrue(
            any(
                phrase in replies["我自己扛就行。"].text
                for phrase in ("不会听你的", "别想一个人牺牲")
            )
        )
        self.assertIn("卡提希娅", replies["芙露德莉斯。"].text)
        self.assertIs(
            replies["芙露德莉斯。"].mode,
            persona.PersonaMode.FLEURDELYS,
        )
        self.assertIn("睡", replies["我要睡觉了。"].text)
        self.assertTrue(
            any(word in replies["任务终于做完了。"].text for word in ("完成", "凯旋"))
        )

    def test_normal_lines_avoid_wrong_relationship_and_tsun_templates(self) -> None:
        lines = [item.text for items in persona.EVENT_LINES.values() for item in items]
        lines.extend(item.text for item in persona.IDLE_DIALOGUES)
        combined = "\n".join(lines)
        for forbidden in ("主人", "遵命", "永远服从", "笨蛋", "才不是", "谁担心你了"):
            self.assertNotIn(forbidden, combined)

    def test_runtime_assets_follow_desktop_pet_contract(self) -> None:
        root = Path(__file__).resolve().parents[1] / "pet-assets" / "cartethyia-chibi"
        expected = {
            "idle": 6, "running-right": 8, "running-left": 8,
            "waving": 4, "jumping": 5, "failed": 8,
            "waiting": 6, "running": 6, "review": 6,
        }
        for state, count in expected.items():
            frames = sorted((root / "frames" / state).glob("*.png"))
            self.assertEqual(len(frames), count, state)
            with Image.open(frames[0]) as frame:
                self.assertEqual(frame.size, (192, 208))
                self.assertEqual(frame.mode, "RGBA")
        with Image.open(root / "spritesheet.webp") as atlas:
            self.assertEqual(atlas.size, (1536, 2288))
            self.assertEqual(atlas.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
