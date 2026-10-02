"""Configuration and navigation for the optional 4C boss challenge entry."""
import time
from pathlib import Path

from PIL import Image


BOSS_AVATARS = {
    "失坠困谷之庭": "warsong_shizhui_kungu.png",
    "虚妄诞生之神": "warsong_xuwang_dansheng.png",
    "星海迷途之扉": "warsong_xinghai_mitu.png",
}
LEVEL_ROWS = {"80": 0.487, "90": 0.565}


class BossChallengeEntrance:
    DEFAULT_LEVEL = "80"
    DEFAULT_TARGET = next(iter(BOSS_AVATARS))
    _RUNTIME_SCREENSHOT = Path(__file__).resolve().parent / "_runtime_screenshot.png"
    BOSS_ENTER_BATTLE_TIMEOUT = 60.0
    BOSS_ENTER_BATTLE_POLL = 0.5
    BOSS_ENTER_BATTLE_CONFIRMATIONS = 2
    BOSS_CHALLENGE_LEVEL_X = 0.125
    BOSS_ENTRY_TIMEOUT = 8.0
    BOSS_CHALLENGE_CONFIRM = (0.800, 0.907)
    BOSS_CHALLENGE_START = (0.859, 0.919)
    BOSS_BOOK_CATEGORY = (0.24, 0.615)
    BOSS_BOOK_TAB = (0.0385, 0.296)
    BOSS_CHALLENGE_X = 0.888
    BOSS_AVATAR_REGION = (0.385, 0.31, 0.464, 0.82)
    BOSS_AVATAR_THRESHOLD = 0.78

    def __init__(
        self, enabled: bool = False, level: str = DEFAULT_LEVEL,
        target: str = DEFAULT_TARGET,
    ):
        """初始化战歌重奏首领入口。

        Args:
            enabled: 是否在 4C 刷取前进入指定首领。
            level: 战歌重奏的推荐等级。
            target: 要挑战的首领名称。

        Raises:
            ValueError: 开关类型、推荐等级或目标首领无效。
        """
        if type(enabled) is not bool:
            raise ValueError("战歌重奏开关必须是布尔值。")
        if not isinstance(level, str) or level not in LEVEL_ROWS:
            raise ValueError(f"不支持的战歌重奏等级：{level}")
        if not isinstance(target, str) or target not in BOSS_AVATARS:
            raise ValueError(f"不支持的战歌重奏目标：{target}")
        self.enabled = enabled
        self.level = level
        self.target = target

    def wait_for_battle(self, runner, timeout: float | None = None) -> bool:
        """等待副本加载完成并确认进入战斗。

        Args:
            runner: 提供截图、首领状态检测和停止信号的任务运行器。
            timeout: 最长等待秒数；为 None 时使用默认超时时间。

        Returns:
            检测到首领名称或血条时返回 True；取消或超时时返回 False。
        """
        screenshot = self._RUNTIME_SCREENSHOT
        limit = self.BOSS_ENTER_BATTLE_TIMEOUT if timeout is None else timeout
        started = time.monotonic()
        last_progress = started
        confirmations = 0
        runner.log(f"    战歌重奏：副本正在加载，等待进入战斗（最多 {limit:.0f} 秒）。")
        while time.monotonic() - started < limit:
            if runner.stop_event.is_set():
                return False
            if runner._inspect_4c_boss_header(screenshot, 0, 0, log_result=False, tolerate_blank=True):
                confirmations += 1
                if confirmations >= self.BOSS_ENTER_BATTLE_CONFIRMATIONS:
                    elapsed = time.monotonic() - started
                    runner.log(f"    战歌重奏：已进入战斗，检测到首领名字/血条（用时 {elapsed:.1f} 秒）。")
                    return True
            else:
                confirmations = 0
                now = time.monotonic()
                if now - last_progress >= 10.0:
                    last_progress = now
                    runner.log(f"    战歌重奏：仍在加载，已等待 {now - started:.0f} 秒。")
            runner._sleep_interruptible(self.BOSS_ENTER_BATTLE_POLL)
        runner.log(f"    战歌重奏：等待进入战斗超时（{limit:.0f} 秒），未检测到首领名字/血条。")
        return False

    def enter(self, runner) -> bool:
        """进入指定的战歌重奏首领并等待战斗开始。

        Args:
            runner: 提供游戏输入、截图检测和停止信号的任务运行器。

        Returns:
            成功进入战斗或入口未启用时返回 True；任务取消时返回 False。

        Raises:
            RuntimeError: 未找到目标首领，或等待进入战斗超时。
        """
        if runner.stop_event.is_set():
            return False
        if not self.enabled:
            return True
        runner.log("    战歌重奏：打开索拉指南。")
        runner.controller.press_key("F2", 100)
        runner._sleep_interruptible(1.5)
        for label, position in (
            ("切换到「讨伐强敌」标签", self.BOSS_BOOK_TAB),
            ("选择「战歌重奏」分类", self.BOSS_BOOK_CATEGORY),
        ):
            if runner.stop_event.is_set():
                return False
            runner.log(f"    战歌重奏：{label}。")
            runner._tap_ratio(*position, 0.8)

        deadline = time.monotonic() + self.BOSS_ENTRY_TIMEOUT
        row_ratio = None
        while time.monotonic() < deadline and not runner.stop_event.is_set():
            row_ratio = self.entry_row_ratio(runner)
            if row_ratio is not None:
                break
            runner._sleep_interruptible(self.BOSS_ENTER_BATTLE_POLL)
        if runner.stop_event.is_set():
            return False
        if row_ratio is None:
            raise RuntimeError(f"未定位到「{self.target}」条目，已停止4C刷取。")

        for label, position, pause in (
            (f"挑战「{self.target}」", (self.BOSS_CHALLENGE_X, row_ratio), 2.0),
            (f"选择推荐等级{self.level}",
             (self.BOSS_CHALLENGE_LEVEL_X, LEVEL_ROWS[self.level]), 0.5),
            ("点击单人挑战", self.BOSS_CHALLENGE_CONFIRM, 1.0),
            ("点击开启挑战", self.BOSS_CHALLENGE_START, 2.0),
        ):
            if runner.stop_event.is_set():
                return False
            runner.log(f"    战歌重奏：{label}。")
            runner._tap_ratio(*position, pause)
        if runner.stop_event.is_set():
            return False
        if self.wait_for_battle(runner):
            return not runner.stop_event.is_set()
        if runner.stop_event.is_set():
            return False
        raise RuntimeError("战歌重奏进入战斗超时，已停止4C刷取；请检查游戏画面后重试。")

    def entry_row_ratio(self, runner) -> float | None:
        """根据首领头像定位对应的挑战条目。

        Args:
            runner: 提供截图和模板匹配能力的任务运行器。

        Returns:
            「直接挑战」按钮的纵坐标比例；未找到首领头像时返回 None。
        """
        screenshot = self._RUNTIME_SCREENSHOT
        template = BOSS_AVATARS[self.target]
        runner._capture_for_matching(screenshot)
        with Image.open(screenshot) as captured:
            width, height = captured.size
        left, top, right, bottom = self.BOSS_AVATAR_REGION
        region = (
            round(width * left), round(height * top),
            round(width * right), round(height * bottom),
        )
        match = runner._find_daily_template(
            template, threshold=self.BOSS_AVATAR_THRESHOLD, region=region, screenshot=screenshot,
        )
        if match is None:
            return None
        return (match.y + match.height / 2) / height
