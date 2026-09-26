from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock

from local_agent import LocalAgentConfig, LocalCartethyiaAgent
from sillytavern_bridge import SillyTavernBridge


ROOT = Path(__file__).resolve().parents[1]


class SillyTavernBridgeTests(unittest.TestCase):
    def test_loopback_round_trip_requires_key(self) -> None:
        bridge = SillyTavernBridge("test-secret", port=0)
        bridge.start()
        try:
            base = f"http://127.0.0.1:{bridge.port}"
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(base + "/next", timeout=2)
            self.assertEqual(denied.exception.code, 401)

            result = {}
            thread = threading.Thread(target=lambda: result.update(text=bridge.ask("你在哪里上学？", "爱弥斯", [], 3)))
            thread.start()
            headers = {"Authorization": "Bearer test-secret"}
            with urllib.request.urlopen(urllib.request.Request(base + "/next", headers=headers), timeout=2) as response:
                item = json.load(response)["request"]
            self.assertEqual(item["character"], "爱弥斯")
            self.assertEqual(item["message"], "你在哪里上学？")
            body = json.dumps({"id": item["id"], "text": "我以前在星炬学院。"}).encode()
            request = urllib.request.Request(base + "/reply", data=body, headers={**headers, "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=2):
                pass
            thread.join(3)
            self.assertEqual(result["text"], "我以前在星炬学院。")
        finally:
            bridge.stop()

    def test_agent_uses_tavern_for_chat_but_routes_explicit_tasks_locally(self) -> None:
        bridge = Mock()
        bridge.ask.return_value = "我以前在星炬学院，现在已经是电子幽灵啦。"
        config = LocalAgentConfig(enabled=True, provider="sillytavern", bridge_token="test")
        agent = LocalCartethyiaAgent(config, "爱弥斯", character_name="爱弥斯", bridge=bridge)
        reply = agent.respond("你在哪里上学？")
        self.assertIn("星炬学院", reply.text)
        self.assertEqual(bridge.ask.call_args.args[1], "爱弥斯")
        task = agent.respond("帮我做做日常")
        self.assertEqual(task.tool, "run_daily")
        bridge.ask.assert_called_once()

    def test_all_four_cards_have_plot_and_valid_v2_fields(self) -> None:
        for name in ("达妮娅", "爱弥斯", "景燃", "卡提希娅"):
            with self.subTest(name=name):
                data = json.loads((ROOT / "sillytavern-cards" / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(data["spec"], "chara_card_v2")
                self.assertEqual(data["spec_version"], "2.0")
                card = data["data"]
                self.assertEqual(card["name"], name)
                self.assertIn("【游戏剧情与当前身份】", card["description"])
                self.assertIn("【wwbs 项目后续关系】", card["description"])
                self.assertIn("剧情后", card["scenario"])
                self.assertTrue(card["character_book"]["entries"])
                self.assertTrue(card["first_mes"])
        aemeath = json.loads((ROOT / "sillytavern-cards" / "爱弥斯.json").read_text(encoding="utf-8"))["data"]
        self.assertIn("星炬学院拉贝尔学部", aemeath["description"])
        self.assertIn("电子幽灵", aemeath["description"])
        self.assertIn("不能说自己现在正在某所理工大学", aemeath["description"])
        anchors = {
            "达妮娅": ("阿列夫一", "西格莉卡", "有心就有选择权"),
            "爱弥斯": ("纸飞机", "拉贝尔学部", "电子幽灵"),
            "景燃": ("烟舒", "阿念", "《寻幽记》"),
            "卡提希娅": ("埃格拉", "芙露德莉斯", "流浪骑士"),
        }
        for name, terms in anchors.items():
            description = json.loads((ROOT / "sillytavern-cards" / f"{name}.json").read_text(encoding="utf-8"))["data"]["description"]
            for term in terms:
                with self.subTest(name=name, term=term):
                    self.assertIn(term, description)


if __name__ == "__main__":
    unittest.main()
