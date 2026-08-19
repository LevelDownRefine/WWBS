from __future__ import annotations

import json
import random
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import aemeath_persona as persona
import daniya_persona


class AemeathPersonaTests(unittest.TestCase):
    def test_prompt_layers_exist(self) -> None:
        self.assertIn("爱弥斯", persona.SYSTEM_PROMPT)
        self.assertIn("校园", persona.CHARACTER_PROMPT)
        self.assertIn("35%", persona.PERSONALITY_PROMPT)
        self.assertIn("主动分享", persona.DIALOGUE_PROMPT)

    def test_every_business_event_renders_and_has_a_valid_action(self) -> None:
        for event in persona.EVENT_LINES:
            values = {"detail": "测试原因"} if "detail" in persona.EVENT_LINES[event][0].text else {}
            dialogue = persona.event_dialogue(event, **values)
            self.assertTrue(dialogue.text.strip(), event)
            valid_actions = set(persona.ACTION_BY_EMOTION.values()) | {"failed", "running"}
            self.assertIn(dialogue.action, valid_actions)

    def test_proactive_dialogue_keeps_vulnerability_rare(self) -> None:
        random.seed(137)
        engine = persona.DialogueEngine()
        samples = [engine.proactive(datetime(2026, 8, 19, 14, 0)) for _ in range(10000)]
        vulnerable = sum(line.emotion is persona.Emotion.VULNERABLE for line in samples)
        self.assertLess(vulnerable / len(samples), 0.02)

    def test_emitted_lines_avoid_forbidden_relationship_templates(self) -> None:
        forbidden = ("主人", "爸爸", "妈妈", "本小姐", "杂鱼", "爱你哦♡")
        texts = [line.text for options in persona.EVENT_LINES.values() for line in options]
        texts += [line.text for options in persona.TIME_LINES.values() for line in options]
        texts += [line.text for options in persona.PROACTIVE_LINES.values() for line in options]
        texts += [line.text for options in persona.AFFECTION_LINES.values() for line in options]
        texts += [line.text for options in persona.USER_REPLY_LINES.values() for line in options]
        self.assertFalse(any(word in text for text in texts for word in forbidden))

    def test_requested_relationship_regression_messages(self) -> None:
        messages = (
            "我回来了。",
            "我要出去一下。",
            "今天不想理你。",
            "我有点累。",
            "我考试考砸了。",
            "你想我了吗？",
            "我想你了。",
            "我要睡觉了。",
            "我三天没打开你。",
            "夸夸我。",
            "你今天想干嘛？",
            "我先去忙了。",
        )
        engine = persona.DialogueEngine()
        for message in messages:
            reply = engine.respond(message)
            self.assertTrue(reply.text.strip(), message)
            self.assertNotIn("随你", reply.text, message)
            self.assertNotIn("无需顾虑", reply.text, message)

    def test_return_lines_are_openly_happy(self) -> None:
        for line in persona.WELCOME_LINES + persona.LONG_ABSENCE_LINES:
            self.assertIs(line.emotion, persona.Emotion.HAPPY)
            self.assertTrue(any(marker in line.text for marker in ("！", "想", "话", "陪")))

    def test_owner_address_weight_is_higher_for_both_pets(self) -> None:
        random.seed(1377)
        aemeath_samples = [persona.idle_dialogue().text for _ in range(2000)]
        daniya_samples = [daniya_persona.idle_line() for _ in range(2000)]
        aemeath_ratio = sum("漂泊者" in text for text in aemeath_samples) / len(aemeath_samples)
        daniya_ratio = sum("漂泊者" in text for text in daniya_samples) / len(daniya_samples)
        self.assertGreater(aemeath_ratio, 0.35)
        self.assertGreater(daniya_ratio, 0.35)
        self.assertLess(aemeath_ratio, 0.65)
        self.assertLess(daniya_ratio, 0.65)

    def test_long_absence_selects_a_return_line(self) -> None:
        now = datetime(2026, 8, 19, 12, 0)
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(
                json.dumps({"last_seen": (now - timedelta(days=4)).timestamp()}),
                encoding="utf-8",
            )
            with patch.object(persona, "STATE_FILE", state_file):
                dialogue = persona.DialogueEngine().welcome(now)
        self.assertIn(dialogue, persona.LONG_ABSENCE_LINES)


if __name__ == "__main__":
    unittest.main()
