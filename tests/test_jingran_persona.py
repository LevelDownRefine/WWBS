from __future__ import annotations

import unittest
from unittest.mock import patch

import jingran_persona as persona


class JingranPersonaTests(unittest.TestCase):
    def test_signature_line_is_preserved(self) -> None:
        self.assertIn(
            "行于阴阳未判之处，踏遍祸福未卜之途，借阴路而行，自也向死地而生。",
            persona.IDLE_LINES,
        )

    def test_required_events_render(self) -> None:
        required = {
            "task_start",
            "task_complete",
            "check_start",
            "check_success",
            "check_failure",
            "diagnose_start",
            "diagnose_error",
            "diagnose_warning",
            "diagnose_ok",
            "stop_requested",
            "mouse_move_failed",
        }
        self.assertTrue(required.issubset(persona.EVENT_LINES))
        for event in required:
            values = {"detail": "测试原因"} if event in {"diagnose_error", "diagnose_warning"} else {}
            self.assertTrue(persona.event_line(event, **values).strip())

    def test_prompt_layers_define_the_requested_character(self) -> None:
        prompts = "\n".join(
            (
                persona.SYSTEM_PROMPT,
                persona.CHARACTER_PROMPT,
                persona.PERSONALITY_PROMPT,
                persona.DIALOGUE_PROMPT,
            )
        )
        for anchor in ("寻幽客", "《寻幽记》", "同行者", "不怕死", "现代自然口语"):
            self.assertIn(anchor, prompts)

    def test_idle_actions_are_exhausted_before_repeating(self) -> None:
        persona._idle_action_bag.clear()
        actions = {persona.idle_line().action for _ in persona.IDLE_ACTIONS}
        self.assertEqual(actions, set(persona.IDLE_ACTIONS))

    def test_real_user_prompts_all_have_scene_specific_replies(self) -> None:
        messages = (
            "我回来了。", "我三天没打开你。", "你想我了吗？", "我想你了。",
            "陪我一会儿。", "我今天心情不好。", "我失败了。", "我不想干了。",
            "我好累。", "我要熬夜。", "你怕死吗？", "你为什么总往危险地方跑？",
            "给我讲个鬼故事。", "鬼猫挈灯是谁？", "你写不出来了吗？",
            "你是不是喜欢一个人？", "下次带我一起去吧。", "我喜欢你。",
            "这个程序又报错了。", "你信神吗？",
        )
        with patch.object(persona.ENGINE, "proactive", side_effect=AssertionError("fell back")):
            for message in messages:
                with self.subTest(message=message):
                    reply = persona.respond_to_user(message)
                    self.assertTrue(reply.text.strip())

    def test_story_writing_death_and_danger_have_correct_tone(self) -> None:
        story = persona.respond_to_user("给我讲个鬼故事").text
        self.assertTrue(any(word in story for word in ("旧钟", "荒宅", "脚步声", "门")))
        writing = persona.respond_to_user("你写不出来了吗").text
        self.assertTrue(any(word in writing for word in ("写不出来", "半页", "能用")))
        death = persona.respond_to_user("你怕死吗").text
        self.assertTrue(any(word in death for word in ("活着", "不怕死", "值得")))
        danger = persona.respond_to_user("你为什么总往危险地方跑").text
        self.assertTrue(any(word in danger for word in ("答案", "值得", "门")))

    def test_generated_dialogue_avoids_banned_templates(self) -> None:
        banned = (
            "主人", "救世主大人", "我只服从你", "呵，有趣", "本座", "贫道", "阁下",
            "桀桀桀", "天机不可泄露", "道友请留步", "这个世界毫无意义", "我想死",
            "死了也无所谓", "别拖我后腿", "宝贝", "亲爱的",
        )
        corpus = [item.text for group in persona.EVENT_LINES.values() for item in group]
        corpus += [item.text for item in persona.IDLE_DIALOGUES]
        corpus += [item.text for item in persona.WELCOME_LINES + persona.LONG_ABSENCE_LINES]
        corpus += [item.text for group in persona.AFFECTION_LINES.values() for item in group]
        corpus += [item.text for group in persona.USER_REPLY_LINES.values() for item in group]
        corpus += [item.text for item in persona.STORY_LINES + persona.WRITING_LINES]
        for line in corpus:
            for phrase in banned:
                self.assertNotIn(phrase, line)

    def test_address_policy_is_not_master_or_fixed_title(self) -> None:
        self.assertEqual(persona.address_for("daily"), "你")
        self.assertEqual(persona.address_for("serious", "阿漂"), "阿漂")
        self.assertEqual(persona.address_for("formal_story"), "漂泊者")


if __name__ == "__main__":
    unittest.main()
