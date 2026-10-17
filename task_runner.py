"""任务配置、输入客户端与自动执行流程。"""

import json
import random
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from combat_4c_entrance import BossChallengeEntrance
from combat_rotation import (BattleMonitor, IdleAttackWorker, RotationClock,
                             SLOT_NAMES, active_modules, default_store)
from image_matcher import TemplateMatcher
from reward_orb_scan import (ORB_DIRECT_CONFIDENCE, ORB_SCAN_STEP,
                             OrbDirectionSweep)
from weekly_rewards import WeeklyLimitReached, WeeklyRewardsVision


APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"

DEFAULT_GROUP_NAME = "幻梦游园"
WEEKLY_TEMPLATE_THRESHOLD = 0.5
CLICK_EDGE_MARGIN_RATIO = 0.10
CLICK_JITTER_RATIO = 0.25
CLICK_DELAY_JITTER_SECONDS = 0.20
CYCLE_PROBE_ATTEMPTS = 5
CYCLE_NEIGHBOR_PROBE_ATTEMPTS = 2
CYCLE_PROBE_INTERVAL = 0.15
WEEKLY_CLICK_INTERVAL = 0.30
WEEKLY_CLICK_JITTER = 0.02
WEEKLY_STABLE_INTERVAL = 0.15
WEEKLY_RESPONSE_TIMEOUT = 4.0
DAILY_REWARD_ORB_MIN_CONFIDENCE = 0.45
CYCLE_FINAL_MAX_RETRIES = 2

# “一键日常”无音区使用精确名称匹配。相似名称（尤其荒石高地 I / II）
# 必须各自对应独立模板，避免滑动列表时误点相邻条目。
DAILY_ZONE_TEMPLATES = {
    "沉心域无音区": "zone_chenxin_yu.png",
    "烬心域无音区": "zone_jinxin_yu.png",
    "方擎西峰无音区": "zone_fangqing_xifeng.png",
    "玄幽东岳无音区": "zone_xuanyou_dongyue.png",
    "落日堤屿无音区": "zone_luori_diyu.png",
    "冰原运输港无音区": "zone_bingyuan_yunshugang.png",
    "加拉尔冠阶无音区": "zone_jialaer_guanxie.png",
    "隐喙深腹无音区": "zone_yinhui_shenfu.png",
    "陷足流川无音区": "zone_xianzu_liuchuan.png",
    "哀恸谷无音区": "zone_aitong_gu.png",
    "贝奥海域无音区": "zone_beiao_haiyu.png",
    "黎乔利群岛无音区": "zone_liqiaoli_qundao.png",
    "榄生半岛无音区": "zone_lansheng_bandao.png",
    "悲叹墓岛无音区": "zone_beitan_mudao.png",
    "中曲台地无音区": "zone_zhongqu_taidi.png",
    "荒石高地无音区 I": "zone_huangshi_gaodi_1.png",
    "虎口山脉无音区": "zone_hukou_shanmai.png",
    "怨鸟泽无音区": "zone_yuanniao_ze.png",
    "归墟港市无音区": "zone_guixu_gangshi.png",
    "荒石高地无音区 II": "zone_huangshi_gaodi_2.png",
    "无光之森无音区": "zone_wuguang_zhisen.png",
}
DAILY_ZONE_NAMES = tuple(DAILY_ZONE_TEMPLATES)
# The new references are tight title crops; their row buttons sit lower.
DAILY_ZONE_BUTTON_Y_OFFSETS = {"zone_chenxin_yu.png": 37, "zone_jinxin_yu.png": 37}


@dataclass
class Step:
    action: str
    label: str = ""
    template: str = ""
    templates: list[str] = field(default_factory=list)
    template_offsets: dict[str, dict[str, int]] = field(default_factory=dict)
    loop: bool = False
    skip_missing: bool = True
    threshold: float = 0.82
    timeout: float = 8.0
    offset_x: int = 0
    offset_y: int = 0
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int = 300
    seconds: float = 0.8
    text: str = ""


@dataclass
class WeeklyTask:
    name: str
    enabled: bool = True
    weekday: str = "any"
    description: str = ""
    template_group: str = "default"
    steps: list[Step] = field(default_factory=list)


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[WeeklyTask]:
        if not self.path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.path}")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        tasks = []
        for item in raw.get("tasks", []):
            steps = [Step(**step) for step in item.get("steps", [])]
            tasks.append(
                WeeklyTask(
                    name=item["name"],
                    enabled=item.get("enabled", True),
                    weekday=item.get("weekday", "any"),
                    description=item.get("description", ""),
                    template_group=item.get("template_group", "default"),
                    steps=steps,
                )
            )
        return tasks

    def save(self, tasks: list[WeeklyTask]) -> None:
        payload = {
            "version": 1,
            "reset_hint": "鸣潮国服常见周刷新为周一 04:00；如你的服务器不同，请按实际情况改任务 weekday。",
            "tasks": [
                {
                    "name": task.name,
                    "enabled": task.enabled,
                    "weekday": task.weekday,
                    "description": task.description,
                    "template_group": task.template_group,
                    "steps": [step.__dict__ for step in task.steps],
                }
                for task in tasks
            ],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class AdbClient:
    def __init__(self, adb_path: str = "adb", device: str = ""):
        self.adb_path = adb_path.strip() or "adb"
        self.device = device.strip()

    def _base_cmd(self) -> list[str]:
        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        return cmd

    def run(self, args: list[str], timeout: int = 15) -> str:
        result = subprocess.run(
            self._base_cmd() + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise RuntimeError(output or f"ADB 命令失败: {' '.join(args)}")
        return output

    def devices(self) -> str:
        return self.run(["devices"])

    def tap(self, x: int, y: int) -> None:
        self.run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x: int, y: int, x2: int, y2: int, duration_ms: int) -> None:
        self.run(["shell", "input", "swipe", str(x), str(y), str(x2), str(y2), str(duration_ms)])

    def text(self, value: str) -> None:
        escaped = value.replace(" ", "%s")
        self.run(["shell", "input", "text", escaped])

    def screencap(self, target: Path) -> None:
        data = subprocess.run(
            self._base_cmd() + ["exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if data.returncode != 0:
            raise RuntimeError(data.stderr.decode("utf-8", errors="replace") or "截图失败")
        target.write_bytes(data.stdout)


class TaskRunner:
    ATTACK_CLICK_INTERVAL = 0.150
    MAIN_ATTACK_CLICK_INTERVAL = ATTACK_CLICK_INTERVAL
    HEAVY_ATTACK_EVERY = 15
    HEAVY_ATTACK_HOLD_MS = 800
    MAIN_Q_INTERVAL = 20.0
    COMBAT_ULTIMATE_INTERVAL = 15.0
    ECHO_ACTION_SETTLE_DELAY = 1.0
    ULTIMATE_INDICATOR_REGION = (0.755, 0.74, 0.875, 0.95)
    ULTIMATE_RING_MIN_SATURATION = 0.27
    ULTIMATE_RING_MIN_COLOR_COVERAGE = 0.30
    ULTIMATE_RING_MIN_BRIGHTNESS = 0.58
    HEAL_ROTATION_INTERVAL = 9.0
    HEAL_SWITCH_SETTLE_DELAY = 2.0
    HEAL_ATTACK_CLICK_INTERVAL = ATTACK_CLICK_INTERVAL
    HEAL_RETURN_DELAY = 1.0
    HEAL_ATTACK_TO_Q_DELAY = 0.30
    HEAL_Q_TO_RETURN_DELAY = 0.80
    REWARD_INITIAL_CHECK_DELAY = 0.15
    REWARD_SEARCH_TURN_PIXELS = 950
    REWARD_SEARCH_TIMEOUT = 90.0
    EMPTY_HEALTH_CONFIRMATIONS = 3
    EMPTY_HEALTH_CONFIRMATION_INTERVAL = 0.15
    BOSS_HEADER_CHECK_INTERVAL = 0.15
    DAILY_BATTLE_END_CHECK_INTERVAL = 1.0
    DAILY_TASK_MISSING_CONFIRMATIONS = 3
    DAILY_TASK_MISSING_CONFIRMATION_INTERVAL = 0.75
    ABSORB_PROMPT_TEMPLATES = ("absorb_prompt_dark.png", "absorb_prompt.png")
    ABSORB_TEXT_CROPS = {
        "absorb_prompt_dark.png": (130, 19, 198, 69),
        "absorb_prompt.png": (122, 10, 193, 59),
    }

    def __init__(
        self,
        controller,
        log,
        dry_run: bool = True,
        stop_event: threading.Event | None = None,
        max_cycles: int | None = None,
        combat_skill_key: str = "E",
        combat_ultimate_key: str = "R",
        daily_zone_name: str = "",
        daily_heal_enabled: bool = False,
        notice=None,
        rotation_modules: list[dict] | None = None,
        rotation_presets: dict[str, list[dict]] | None = None,
        rotation_times: dict[str, dict] | None = None,
        rotation_orders: dict[str, list[int]] | None = None,
        boss_challenge: BossChallengeEntrance | None = None,
    ):
        self.controller = controller
        self.log = log
        self.dry_run = dry_run
        self.stop_event = stop_event or threading.Event()
        self.max_cycles = max_cycles
        self.combat_skill_key = combat_skill_key
        self.combat_ultimate_key = combat_ultimate_key
        self.daily_zone_name = daily_zone_name
        self.daily_heal_enabled = bool(daily_heal_enabled)
        self.boss_challenge = boss_challenge
        self.notice = notice or (lambda _message: None)
        self.rotation_modules = rotation_modules if rotation_modules is not None else active_modules(default_store())
        self.rotation_presets = rotation_presets or {}
        self.rotation_times = rotation_times or {}
        self.rotation_orders = rotation_orders or {}
        self._rotation_slot = 1
        self._rotation_end_check = None
        self._rotation_battle_finished = False
        self._combat_animation_until = 0.
        self._combat_input_cancel = threading.Event()
        self._rotation_continuous_started = False
        self.matcher = TemplateMatcher(TEMPLATES_DIR)
        self.template_root = TEMPLATES_DIR
        self.debug_matches = False
        self.last_clicked_image_step: Step | None = None
        self._weekly_monitoring = False
        self.weekly_rewards_pending = False
        self._weekly_observed_target = None
        self._weekly_pending_click = None
        self._weekly_click_at = 0.

    def run_task(self, task: WeeklyTask) -> None:
        self._weekly_monitoring = task.template_group == "default" and task.name == DEFAULT_GROUP_NAME
        try:
            if self._weekly_monitoring and not self.dry_run:
                screenshot = APP_DIR / "_runtime_screenshot.png"
                self._capture_for_matching(screenshot)
                self._check_weekly_cap(screenshot)
            self._run_task_impl(task)
        except WeeklyLimitReached:
            self.log("周常已达到本周上限，已结束循环并返回周度游历。")
        finally:
            self._weekly_monitoring = False

    def _run_task_impl(self, task: WeeklyTask) -> None:
        group_dir = TEMPLATES_DIR / task.template_group if task.template_group != "default" else TEMPLATES_DIR
        if not group_dir.exists():
            raise FileNotFoundError(f"模板组不存在: {task.template_group}")
        self.template_root = group_dir
        self.matcher.templates_dir = group_dir
        self.log(f"使用模板组: {task.template_group}")
        self.log(f"开始任务: {task.name}")
        if self._weekly_monitoring:
            self.log(f"周常局部匹配阈值：{WEEKLY_TEMPLATE_THRESHOLD:.2f}；全局页面定位需要较强文字匹配，连续截图稳定后点击。")
        if self._weekly_monitoring and not self.dry_run:
            cycle = next((step for step in task.steps if step.action == 'tap_image_cycle'), None)
            if cycle is not None:
                start = next((step for step in task.steps if step.action == 'tap_image' and step.template == 'menu1.png'),
                             Step(action='tap_image', template='menu1.png'))
                self._run_weekly_dynamic(start, cycle)
                self.log(f"完成任务: {task.name}")
                return
        for index, step in enumerate(task.steps, start=1):
            if self.stop_event.is_set():
                self.log("收到停止信号，任务已中断。")
                return
            name = step.label or step.action
            self.log(f"  {index}. {name}")
            self._run_step(step)
        self.log(f"完成任务: {task.name}")

    def _run_step(self, step: Step) -> None:
        if step.action == "tap":
            if self.dry_run:
                self.log("    干运行：跳过坐标点击。")
                time.sleep(min(step.seconds, 0.5))
                return
            self._require_xy(step)
            self.controller.tap(step.x, step.y)
            self._sleep_click_interval(step.seconds)
        elif step.action == "tap_image":
            x, y, score = self._find_image(step)
            self.log(f"    找到模板 {step.template}: ({x}, {y}) 相似度 {score:.3f}")
            if self.dry_run:
                self.log("    干运行：已识别位置，但不点击。")
            else:
                self.log(f"    正在点击识别坐标: ({x}, {y})")
                result = (self._click_cycle_template(step, x, y) if self._weekly_monitoring
                          else self.controller.tap(x, y))
                if isinstance(result, dict):
                    self.log(
                        "    鼠标移动结果: "
                        f"目标{result.get('target')}，"
                        f"输入{result.get('input')}，"
                        f"方式{result.get('method')}，"
                        f"窗口{result.get('client')}，"
                        f"截图{result.get('capture')}，"
                        f"区域{result.get('bbox')}，"
                        f"移动前{result.get('before')}，"
                        f"移动后{result.get('after_move')}，"
                        f"SetCursorPos={result.get('set_cursor_ok')}"
                    )
                    if not result.get("set_cursor_ok"):
                        self.log("    鼠标没有移动成功：请尝试右键桌面快捷方式，以管理员身份运行。")
                elif result:
                    self.log(f"    已发送点击，屏幕坐标: {result}")
                self.last_clicked_image_step = step
            self._sleep_click_interval(step.seconds)
        elif step.action == "tap_image_cycle":
            self._run_image_cycle(step)
        elif step.action == "move_to_visual_target":
            self._run_visual_navigation(step)
        elif step.action == "combat_4c":
            self._run_4c_combat(step)
        elif step.action == "tower_challenge":
            self._run_tower_challenge(step)
        elif step.action == "daily_routine":
            self._run_daily_routine(step)
        elif step.action == "swipe":
            if self.dry_run:
                self.log("    干运行：跳过滑动。")
                time.sleep(min(step.seconds, 0.5))
                return
            if None in (step.x, step.y, step.x2, step.y2):
                raise ValueError("swipe 步骤需要 x/y/x2/y2")
            self.controller.swipe(step.x, step.y, step.x2, step.y2, step.duration_ms)
            time.sleep(step.seconds)
        elif step.action == "wait":
            time.sleep(step.seconds)
        elif step.action == "text":
            if self.dry_run:
                self.log("    干运行：跳过文本输入。")
                time.sleep(min(step.seconds, 0.5))
                return
            self.controller.text(step.text)
            time.sleep(step.seconds)
        else:
            raise ValueError(f"未知步骤类型: {step.action}")

    def _tower_template_present(self, screenshot: Path, name: str, region) -> bool:
        with Image.open(screenshot) as source:
            width, height = source.size
        scale = min(height, width*9/16) / 1080
        return self._find_daily_template(
            str(TEMPLATES_DIR / "tower" / name), threshold=.86,
            region=tuple(round(v * (width if i % 2 == 0 else height)) for i, v in enumerate(region)),
            scales=[scale, scale*.97, scale*1.03], screenshot=screenshot,
        ) is not None

    def _tower_success_present(self, screenshot: Path) -> bool:
        return (self._tower_template_present(screenshot, "success_title.png", (.35, .18, .65, .40))
                and self._tower_template_present(screenshot, "confirm_score.png", (.35, .76, .66, .94)))

    def _approach_tower_start(self, screenshot: Path) -> bool:
        """Return True only if the challenge was started; never press F blindly."""
        deadline = time.monotonic() + 45
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            self._capture_for_matching(screenshot)
            if self._tower_success_present(screenshot):
                self.log("    已显示深塔挑战成功，保持结算界面。")
                return False
            if self._tower_template_present(screenshot, "start_prompt.png", (.50, .32, .95, .75)):
                if self.stop_event.is_set():
                    return False
                self.controller.release_keys()
                self.controller.press_key("F", 100)
                self.log("    已识别“开始挑战”，按 F 开始深塔挑战。")
                self._sleep_interruptible(.4)
                return not self.stop_event.is_set()
            target_x, _target_y, _confidence = self._daily_reward_orb_location(screenshot)
            with Image.open(screenshot) as source:
                width = source.width
            keys = ("W",)
            if target_x is not None and abs(target_x-width*.5) > width*.05:
                keys = ("W", "A" if target_x < width*.5 else "D")
            if self.stop_event.is_set():
                return False
            self.controller.press_keys(keys, 300)
            self._sleep_interruptible(.08)
        if self.stop_event.is_set():
            return False
        raise RuntimeError("靠近深塔光球后未识别到“开始挑战”，请从塔内光球前的画面启动。")

    def _run_tower_challenge(self, step: Step) -> None:
        required = ("press_keys", "press_key", "press_binding", "left_click", "hold_left_button",
                    "middle_click", "release_keys")
        if any(not hasattr(self.controller, name) for name in required):
            raise RuntimeError("深塔挑战目前只支持 PC 客户端窗口。")
        if self.dry_run:
            self.log("    干运行：靠近光球，识别开始挑战后按 F，按深塔预设持续战斗至挑战成功。")
            return
        screenshot = APP_DIR / "_runtime_screenshot.png"
        try:
            if self._approach_tower_start(screenshot):
                self._run_tower_battle(step, screenshot)
        finally:
            self.controller.release_keys()

    def _run_tower_battle(self, step: Step, screenshot: Path) -> None:
        modules = self.rotation_presets.get("tower", self.rotation_modules)
        skill = self.controller.normalize_input_binding(self.combat_skill_key)
        ultimate = self.controller.normalize_input_binding(self.combat_ultimate_key)
        self._rotation_slot = None
        self._rotation_battle_finished = False
        self._rotation_end_check = self._tower_success_present
        self._combat_animation_until = 0.
        enabled, lock = threading.Event(), threading.Lock()
        idle = IdleAttackWorker(self.controller, self.stop_event, lock,
                                attack_interval=self.MAIN_ATTACK_CLICK_INTERVAL,
                                heavy_hold_ms=self.HEAVY_ATTACK_HOLD_MS)
        self._rotation_idle_worker = idle
        monitor = None
        try:
            def inspect():
                self._capture_for_matching(screenshot)
                return self._tower_success_present(screenshot)
            initial = inspect()
            if initial:
                self.log("    已识别挑战成功，停止操作并保持结算界面。")
                return
            # The clock's first select action confirms the role before any attack.
            # Confirming here as well would repeat the same two screenshot checks.
            self.controller.middle_click()
            rotation = RotationClock(modules, time.monotonic(), self.MAIN_ATTACK_CLICK_INTERVAL,
                                     self.rotation_times.get("tower"), background_idle=True,
                                     slot_order=self.rotation_orders.get("tower"))
            monitor = BattleMonitor(inspect, initial, self.stop_event)
            deadline = time.monotonic() + max(180, step.timeout)
            checked_at = 0.0
            while not self.stop_event.is_set() and time.monotonic() < deadline:
                checked = monitor.poll()
                if checked is not None:
                    checked_at = time.monotonic()
                    if checked[0]:
                        idle.pause()
                        monitor.pause()
                        enabled.clear()
                        self.controller.release_keys()
                        self.log("    深塔挑战成功，停止战斗；不点击确认成绩，保持结算界面。")
                        return
                elif time.monotonic()-checked_at >= .4:
                    monitor.request()
                if not self._run_rotation_action(rotation.next_action(time.monotonic()), rotation,
                                                 skill, ultimate, enabled, lock):
                    return
                self._sleep_interruptible(.025)
            if not self.stop_event.is_set():
                raise RuntimeError("深塔挑战达到安全时限，未识别到挑战成功，已停止操作。")
        finally:
            idle.close()
            self._rotation_end_check = None
            self._rotation_idle_worker = None
            enabled.clear()
            self.controller.release_keys()
            if monitor is not None:
                monitor.close()
                if monitor.error is not None:
                    raise RuntimeError(f"深塔画面检查失败：{monitor.error}") from monitor.error
            if idle.error is not None:
                raise RuntimeError(f"深塔战斗输入失败：{idle.error}") from idle.error

    def _run_4c_combat(self, step: Step) -> None:
        required = (
            "press_keys",
            "press_key",
            "press_binding",
            "left_click",
            "hold_left_button",
            "middle_click",
            "wheel_at",
            "move_mouse_relative",
            "release_keys",
        )
        if any(not hasattr(self.controller, name) for name in required):
            raise RuntimeError("4C刷取目前只支持 PC 客户端窗口。")
        skill_key = self.controller.normalize_input_binding(self.combat_skill_key)
        ultimate_key = self.controller.normalize_input_binding(self.combat_ultimate_key)
        cycle_count = max(1, int(self.max_cycles or 1))
        if self.dry_run:
            self.log(
                f"    干运行：计划执行 {cycle_count} 轮；每轮开打先按鼠标中键锁定敌人，"
                f"然后按4C预设依次执行 {len(self.rotation_presets.get('combat_4c', self.rotation_modules))} 个模块；"
                f"技能键 {skill_key}，大招键 {ultimate_key}。"
            )
            return

        self.log(
            f"    4C刷取已开始：共 {cycle_count} 轮，当前技能键位 {skill_key}，"
            f"大招键位 {ultimate_key}。"
        )
        try:
            if self.boss_challenge is not None and not self.boss_challenge.enter(self):
                return
            for cycle_index in range(1, cycle_count + 1):
                if self.stop_event.is_set():
                    self.log("    收到停止信号，4C刷取已停止。")
                    return
                self.log(f"    === 第 {cycle_index}/{cycle_count} 轮 ===")
                self._run_4c_battle(step, skill_key, ultimate_key, cycle_index)
                if self.stop_event.is_set():
                    return
                self._collect_4c_reward(cycle_index)
                if self.stop_event.is_set():
                    return
                if cycle_index >= cycle_count:
                    self.log(f"    已完成 {cycle_count} 轮战斗与吸收，停止4C刷取。")
                    return
                self._restart_4c_challenge(cycle_index + 1)
                if self.boss_challenge is not None:
                    self.boss_challenge.wait_for_battle(self)
        finally:
            try:
                self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3", "4"))
            except Exception as exc:
                self.log(f"    释放战斗按键时遇到问题: {exc}")

    def _run_4c_battle(self, step: Step, skill_key: str, ultimate_key: str, cycle_index: int) -> None:
        started = time.monotonic()
        deadline = started + max(30.0, step.timeout)
        modules = self.rotation_presets.get("combat_4c", self.rotation_modules)
        self._rotation_slot = None
        self._rotation_battle_finished = False
        self._rotation_end_check = self._4c_switch_end_present
        self._combat_animation_until = 0.
        self._combat_input_cancel.clear()
        self._rotation_continuous_started = False
        last_header_check = 0.0
        boss_header_seen = False
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self.log(f"    第{cycle_index}轮：鼠标中键锁定敌人。")
        self.controller.middle_click()
        attack_enabled = threading.Event()
        attack_lock = threading.Lock()
        idle_worker = IdleAttackWorker(self.controller, self.stop_event, attack_lock,
                                       attack_interval=self.MAIN_ATTACK_CLICK_INTERVAL,
                                       heavy_hold_ms=self.HEAVY_ATTACK_HOLD_MS,
                                       on_error=lambda exc: self.log(f"    空闲普攻失败：{exc}"))
        self._rotation_idle_worker = idle_worker
        monitor = None
        try:
            inspect = lambda: self._inspect_4c_battle_state(screenshot, cycle_index, 0, log_result=False)
            initial = inspect()
            rotation = RotationClock(modules, time.monotonic(), self.MAIN_ATTACK_CLICK_INTERVAL,
                                     self.rotation_times.get("combat_4c"), background_idle=True,
                                     slot_order=self.rotation_orders.get("combat_4c"))
            def stop_on_prompt(result):
                if result[1]:
                    self._rotation_battle_finished = True
                    self._combat_input_cancel.set()
                    idle_worker.close()
                    attack_enabled.clear()
                    self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3"))
                    self.log(f"    识别到{result[1]}，立即停止战斗输入，进入吸收。")
            monitor = BattleMonitor(inspect, initial, self.stop_event, on_result=stop_on_prompt)
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return
                now = time.monotonic()
                checked = monitor.poll()
                if checked is not None:
                    header_present, reward_hint = checked[0]
                    last_header_check = time.monotonic()
                    if reward_hint:
                        idle_worker.pause()
                        monitor.pause()
                        attack_enabled.clear()
                        self.controller.release_keys()
                        hint = reward_hint if isinstance(reward_hint, str) else "领取奖励"
                        self.log(f"    第{cycle_index}轮：出现{hint}提示，战斗已结束，进入声骸吸收流程。")
                        return
                    elif header_present:
                        boss_header_seen = True
                    elif header_present is None or time.monotonic() < self._combat_animation_until:
                        # Ultimate cutscenes hide the HUD. Keep the current axis
                        # and idle attacks running; this frame is not a defeat.
                        pass
                    elif boss_header_seen:
                        idle_worker.pause()
                        monitor.pause()
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        missing_header_checks = 1
                        self.controller.release_keys()
                        self.log("    战斗监测发现首领名字与血条疑似消失，暂停攻击并快速复核。")
                        while missing_header_checks < self.EMPTY_HEALTH_CONFIRMATIONS:
                            self._sleep_interruptible(self.EMPTY_HEALTH_CONFIRMATION_INTERVAL)
                            header_present, reward_hint = self._inspect_4c_battle_state(
                                screenshot,
                                cycle_index,
                                missing_header_checks,
                            )
                            if reward_hint:
                                self.log(f"    第{cycle_index}轮：复核发现结束提示，进入声骸吸收流程。")
                                return
                            if header_present is None or time.monotonic() < self._combat_animation_until:
                                missing_header_checks = 0
                                break
                            if header_present:
                                missing_header_checks = 0
                                break
                            missing_header_checks += 1
                        if missing_header_checks >= self.EMPTY_HEALTH_CONFIRMATIONS:
                            self.controller.release_keys()
                            self.log(
                                f"    第{cycle_index}轮：已确认首领名字与整条血条彻底消失，进入吸收流程。"
                            )
                            return
                        monitor.resume()
                        last_header_check = time.monotonic()
                    elif now - started >= 15.0:
                        raise RuntimeError("没有检测到屏幕顶部的首领名字和血条，已停止4C刷取。请先进入战斗。")
                elif now - last_header_check >= self.BOSS_HEADER_CHECK_INTERVAL:
                    monitor.request()
                action = rotation.next_action(time.monotonic())
                if not self._run_rotation_action(action, rotation, skill_key, ultimate_key,
                                                 attack_enabled, attack_lock):
                    return
                self._sleep_interruptible(0.025)
            raise RuntimeError("单轮4C战斗达到安全时限，已自动停止。")
        finally:
            idle_worker.close()
            self._rotation_end_check = None
            self._rotation_idle_worker = None
            attack_enabled.clear()
            try:
                self.controller.release_keys()
            finally:
                if monitor is not None:
                    monitor.close()
            if monitor is not None and monitor.error is not None:
                raise RuntimeError(f"战斗画面检查失败：{monitor.error}") from monitor.error
            if idle_worker.error is not None:
                raise RuntimeError(f"空闲普攻失败：{idle_worker.error}") from idle_worker.error

    def _inspect_4c_battle_state(
        self, screenshot: Path, cycle_index: int, missing_checks: int, *, log_result: bool = True,
    ) -> tuple[bool | None, bool | str]:
        # Both signals use the same fresh frame; the reward hint is optional.
        inspected_at = time.monotonic()
        header_present = self._inspect_4c_boss_header(
            screenshot, cycle_index, missing_checks, log_result=log_result,
        )
        if self._4c_reward_hint_present(screenshot):
            return header_present, "领取奖励"
        try:
            with Image.open(screenshot) as captured:
                scale = captured.width / 1920.0
            prompt, _name = self._find_4c_absorb_prompt(screenshot, scale, fast=True)
        except (OSError, ValueError):
            prompt = None
        if prompt is not None:
            return header_present, "吸收"
        if not header_present:
            native_check = callable(getattr(type(self.controller), 'active_character_slot', None))
            if (inspected_at < self._combat_animation_until
                    or (native_check and (not self._overworld_hud_ready(screenshot)
                                          or self.controller.active_character_slot(screenshot) is None))):
                return None, False
        return header_present, False

    def _4c_reward_hint_present(self, screenshot: Path) -> bool:
        try:
            with Image.open(screenshot) as source:
                width, height = source.size
        except (OSError, ValueError):
            return False
        scale = height / 1080.0
        match = self._find_daily_template(
            str(TEMPLATES_DIR / "4c" / "claim_reward_hint.png"), threshold=0.86,
            region=(0, round(height * 0.12), round(width * 0.20), round(height * 0.65)),
            scales=[scale, scale * 0.96, scale * 1.04], screenshot=screenshot,
        )
        return match is not None

    def _inspect_4c_boss_header(
        self,
        screenshot: Path,
        cycle_index: int,
        missing_checks: int,
        *,
        log_result: bool = True,
    ) -> bool:
        """Capture the boss header and report whether its name or full track remains."""
        self._capture_for_matching(screenshot)
        health_ratio = self._boss_health_ratio(screenshot)
        name_ratio = self._boss_name_ratio(screenshot)
        bar_track_score = self._boss_bar_track_score(screenshot)
        header_present = name_ratio >= 0.015 or bar_track_score >= 0.18
        confirmation = 0 if header_present else missing_checks + 1
        if log_result:
            self.log(
                f"    第{cycle_index}轮快速复核：血量色彩 {health_ratio:.3f}，名字 {name_ratio:.3f}，"
                f"血条轨道 {bar_track_score:.3f}"
                f"（完整消失确认 {confirmation}/{self.EMPTY_HEALTH_CONFIRMATIONS}）。"
            )
        return header_present

    def _run_4c_continuous_attack(
        self,
        attack_enabled: threading.Event,
        attack_finished: threading.Event,
        attack_lock: threading.Lock,
        heavy_every: int | None = None,
    ) -> None:
        """Attack on its own clock so screenshots and movement never form click bursts."""
        attack_count = 0
        while not attack_finished.is_set() and not self.stop_event.is_set():
            if not attack_enabled.wait(timeout=0.05):
                continue
            if attack_finished.is_set() or self.stop_event.is_set():
                return
            try:
                with attack_lock:
                    if attack_enabled.is_set():
                        if attack_count >= (heavy_every or self.HEAVY_ATTACK_EVERY):
                            self.controller.hold_left_button(self.HEAVY_ATTACK_HOLD_MS)
                            attack_count = 0
                        else:
                            self.controller.left_click()
                            attack_count += 1
            except Exception as exc:
                self.log(f"    持续普攻失败：{exc}")
                self.stop_event.set()
                return
            attack_finished.wait(self.MAIN_ATTACK_CLICK_INTERVAL)

    def _rotation_first_slot(self, modules: list[dict], mode: str) -> int:
        occupied = {item.get("slot", 1) for item in modules}
        return next(slot for slot in self.rotation_orders.get(mode, [1, 2, 3]) if slot in occupied)

    def _4c_switch_end_present(self, screenshot: Path) -> bool:
        if self._4c_reward_hint_present(screenshot):
            return True
        with Image.open(screenshot) as image:
            scale = image.width / 1920
        return self._find_4c_absorb_prompt(screenshot, scale, fast=True)[0] is not None

    def _read_rotation_slot(self, *, check_end: bool = True) -> int | None:
        screenshot = APP_DIR / '_role_screenshot.png'
        self._capture_for_matching(screenshot)
        observed = self.controller.active_character_slot(screenshot)
        # The first frame checks settlement. On the second, inspect it again only
        # when the HUD disappeared; a valid portrait does not need another full scan.
        if ((check_end or observed is None) and self._rotation_end_check is not None
                and self._rotation_end_check(screenshot)):
            self._rotation_battle_finished = True
            self.log("    切人确认时发现战斗结束，停止切人并进入任务收尾。")
            return None
        return observed

    def _select_rotation_slot(self, slot: int, *, verify: bool = False) -> bool:
        if self.stop_event.is_set():
            return False
        if self._rotation_battle_finished:
            return False
        native_check = callable(getattr(type(self.controller), 'active_character_slot', None))
        if native_check and (verify or self._rotation_slot != slot):
            worker = getattr(self, '_rotation_idle_worker', None)
            owned = not isinstance(worker, IdleAttackWorker)
            if owned:
                worker = IdleAttackWorker(self.controller, self.stop_event, threading.Lock(),
                    attack_interval=self.MAIN_ATTACK_CLICK_INTERVAL,
                    on_error=lambda exc: self.log(f'    切人确认时普攻失败：{exc}'))
            try:
                return self._confirm_rotation_slot(slot, worker)
            finally:
                if owned:
                    worker.close()
                else:
                    worker.pause()
        if self._rotation_slot != slot:
            self.controller.press_key(str(slot), 65)
            self._rotation_slot = slot
        return not self.stop_event.is_set()

    def _confirm_rotation_slot(self, slot, worker):
        deadline = time.monotonic()+6.0
        attempt, observed = 0, None
        while time.monotonic() < deadline and not self.stop_event.is_set():
            observed = self._read_rotation_slot()
            if self._rotation_battle_finished or self.stop_event.is_set():
                return False
            if observed is None and time.monotonic() < self._combat_animation_until:
                self._sleep_interruptible(.08)
                continue
            if observed == slot:
                self._sleep_interruptible(.025)
                if self.stop_event.is_set():
                    return False
                if (self._read_rotation_slot(check_end=False) == slot and not self._rotation_battle_finished
                        and not self.stop_event.is_set()):
                    self._rotation_slot = slot
                    self.log(f"    已确认{SLOT_NAMES[slot]}上场，开始执行该角色模块。")
                    return True
                if self._rotation_battle_finished:
                    return False
            attempt += 1
            with worker.input_lock:
                if self.stop_event.is_set() or self._rotation_battle_finished:
                    return False
                self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3"))
                self.controller.press_key(str(slot), 65)
            worker.arm_switch_confirmation(deadline)
            self.log(f"    请求切到{SLOT_NAMES[slot]}（第{attempt}次），边普攻边确认头像栏。")
            self._sleep_interruptible(.08)
        if self.stop_event.is_set():
            return False
        current = SLOT_NAMES.get(observed, '未识别')
        raise RuntimeError(f"未能确认切到{SLOT_NAMES[slot]}，最后识别为{current}。已停止，不会跳过此角色继续切人。")

    def _run_rotation_action(self, action: dict | None, rotation: RotationClock,
                             skill_key: str, ultimate_key: str,
                             attack_enabled: threading.Event, attack_lock: threading.Lock,
                             *, daily: bool = False, task_seen: bool = True,
                             screenshot: Path | None = None) -> bool:
        if self._rotation_battle_finished or self.stop_event.is_set():
            return False
        if action is None:
            return not self.stop_event.is_set()
        kind, item = action["kind"], action["module"]
        idle_worker = getattr(self, "_rotation_idle_worker", None)
        if kind == "idle_attack":
            if idle_worker is not None and self._rotation_slot == item.get("slot", 1):
                idle_worker.arm(item, rotation.visit_deadline)
            return not self.stop_event.is_set()
        if idle_worker is not None:
            idle_worker.pause()
        attack_enabled.clear()
        if not self._select_rotation_slot(item.get("slot", 1), verify=kind == "select_slot"):
            return False
        if kind == "select_slot":
            rotation.start_visit(time.monotonic())
            return True
        if kind == "wait":
            return True
        if time.monotonic() >= rotation.visit_deadline:
            return True
        if kind == "left_click":
            self.controller.left_click()
        elif kind == "hold_left":
            remaining_ms = max(1, round((rotation.visit_deadline - time.monotonic()) * 1000))
            duration = min(self.HEAVY_ATTACK_HOLD_MS, remaining_ms)
            if callable(getattr(type(self.controller), 'hold_left_button_cancelable', None)):
                self.controller.hold_left_button_cancelable(duration, self._combat_input_cancel)
            else:
                self.controller.hold_left_button(duration)
        elif kind == "jump":
            self.controller.press_key("SPACE", 50)
        elif kind in {"skill", "ultimate", "echo"}:
            if self.stop_event.is_set():
                return False
            rotation.last_run[item["id"]] = time.monotonic()
            explicit_wait = rotation.has_following_wait(time.monotonic())
            idle_module = next((module for module in rotation.columns[rotation.slot]
                                if module['kind'] == 'idle_attack'), None)
            resume_idle = (idle_worker is not None and rotation.background_idle
                           and idle_module is not None and not explicit_wait)
            if kind == "skill":
                self.controller.press_binding(skill_key, 65)
                if not (explicit_wait or resume_idle):
                    self._sleep_interruptible(min(0.20, max(0, rotation.visit_deadline - time.monotonic())))
            elif kind == "ultimate":
                self._cast_timed_ultimate(ultimate_key, attack_enabled, attack_lock, resume_attacks=False,
                                         settle_delay=0 if explicit_wait or resume_idle else min(0.8, max(0, rotation.visit_deadline - time.monotonic())))
            else:
                self.controller.press_key("Q", 120)
                if not (explicit_wait or resume_idle):
                    self._sleep_interruptible(min(self.ECHO_ACTION_SETTLE_DELAY,
                                                  max(0, rotation.visit_deadline - time.monotonic())))
            # Resume only after the cast key is released. Due-module inspection
            # then runs alongside the idle worker; actual actions pause it again.
            if resume_idle and not self.stop_event.is_set() and not self._rotation_battle_finished:
                # Preserve the skill-to-skill cadence, but represent it in the
                # scheduler so idle clicks and ending checks remain responsive.
                delay = {'skill': .2, 'ultimate': .8, 'echo': self.ECHO_ACTION_SETTLE_DELAY}[kind]
                rotation.defer_cast_followup(time.monotonic(), delay)
                idle_worker.arm(idle_module, rotation.visit_deadline)
        elif kind == "approach":
            duration = min(float(item["value"]), max(0, rotation.visit_deadline - time.monotonic()))
            if callable(getattr(type(self.controller), 'press_keys_cancelable', None)):
                self.controller.press_keys_cancelable(("W",), max(1, round(duration*1000)), self._combat_input_cancel)
            else:
                self.controller.press_keys(("W",), max(1, round(duration * 1000)))
        return not self.stop_event.is_set()

    def _run_daily_routine(self, step: Step) -> None:
        """Run the two-round daily tacet-field flow with optional healing."""
        required = (
            "press_keys",
            "press_key",
            "press_binding",
            "left_click",
            "hold_left_button",
            "middle_click",
            "move_mouse_relative",
            "release_keys",
        )
        if any(not hasattr(self.controller, name) for name in required):
            raise RuntimeError("一键日常目前只支持 PC 客户端窗口。")
        template_name = DAILY_ZONE_TEMPLATES.get(self.daily_zone_name)
        if not template_name:
            raise RuntimeError("请先在开始页滑动选择要挑战的无音区。")
        if self.dry_run:
            self.log(
                f"    干运行：将精确寻找“{self.daily_zone_name}”，完成两轮战斗与双倍领取，"
                "随后领取活跃度与先约电台奖励；周度游历未完成时继续执行15轮幻梦游园。"
            )
            return

        skill_key = self.controller.normalize_input_binding(self.combat_skill_key)
        ultimate_key = self.controller.normalize_input_binding(self.combat_ultimate_key)
        self.log(f"    一键日常目标：{self.daily_zone_name}。")
        self.log("    日常战斗将按已分配的预设切换角色并执行模块。")
        try:
            if not self._open_daily_tacet_field(template_name):
                if getattr(self,'_daily_activity_confirmed_full',False):
                    self.log('    已确认当前活跃度达到100，跳过无音区战斗，直接领取任务与宝箱奖励。')
                    self._collect_daily_activity_rewards(already_open=True)
                    if self.stop_event.is_set():
                        return
                    self._collect_daily_battlepass_rewards()
                    if self.stop_event.is_set():
                        return
                    self._continue_daily_into_weekly_travel()
                    return
                completed_message = "今日日常已经完成，不再挑战无音区。"
                self.log(f"    【提示】检测到索拉指南已自动跳过活跃度页面，{completed_message}")
                self.notice(completed_message)
                self._continue_daily_from_open_guide_page()
                self.log("    日常已完成后的周度游历检查结束。")
                return
            for cycle_index in (1, 2):
                if self.stop_event.is_set():
                    return
                self.log(f"    === 一键日常第 {cycle_index}/2 轮 ===")
                while not self.stop_event.is_set():
                    self._run_daily_battle(step, skill_key, ultimate_key, cycle_index)
                    if self.stop_event.is_set():
                        return
                    if self._collect_daily_reward(cycle_index):
                        break
                self._wait_for_daily_success(cycle_index)
                if cycle_index == 1:
                    self._click_daily_template("restart_challenge.png", "重新挑战", timeout=20.0)
                    self._click_optional_daily_template(
                        "insufficient_continue.png",
                        "体力不足继续提示的确认",
                        timeout=5.0,
                    )
                    self._sleep_interruptible(0.3)
                else:
                    self._click_daily_template("exit_instance.png", "退出副本", timeout=20.0)
                    self._confirm_daily_exit_if_present()
                    self._sleep_interruptible(0.3)
            self._collect_daily_activity_rewards()
            self._collect_daily_battlepass_rewards()
            self._continue_daily_into_weekly_travel()
            self.log("    一键日常与自动周常流程完成。")
        finally:
            try:
                self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3", "4"))
            except Exception as exc:
                self.log(f"    释放日常任务按键时遇到问题: {exc}")

    def _capture_size(self, screenshot: Path | None = None) -> tuple[Path, int, int]:
        target = screenshot or (APP_DIR / "_runtime_screenshot.png")
        self._capture_for_matching(target)
        with Image.open(target) as captured:
            width, height = captured.size
        return target, width, height

    @staticmethod
    def _daily_exit_confirmation_present(screenshot: Path) -> bool:
        """Detect the white leave-confirmation panel and its two dark buttons."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]

        def ratio(
            box: tuple[float, float, float, float],
            predicate,
        ) -> float:
            left, top, right, bottom = box
            crop = image[
                round(height * top):round(height * bottom),
                round(width * left):round(width * right),
            ]
            if crop.size == 0:
                return 0.0
            return float(predicate(crop).mean())

        bright_panel = ratio(
            (0.22, 0.29, 0.78, 0.71),
            lambda crop: crop.min(axis=2) > 205,
        )
        left_dark_button = ratio(
            (0.24, 0.59, 0.43, 0.68),
            lambda crop: crop.max(axis=2) < 90,
        )
        right_dark_button = ratio(
            (0.56, 0.59, 0.76, 0.68),
            lambda crop: crop.max(axis=2) < 90,
        )
        return bright_panel > 0.50 and left_dark_button > 0.28 and right_dark_button > 0.28

    def _confirm_daily_exit_if_present(self, timeout: float = 3.0) -> bool:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._daily_exit_confirmation_present(screenshot):
                with Image.open(screenshot) as captured:
                    width, height = captured.size
                self.log("    已识别“确认离开”二次提示，点击右侧确认。")
                self.controller.tap(round(width * 0.657), round(height * 0.628))
                self._sleep_interruptible(0.25)
                return True
            if self._overworld_hud_ready(screenshot):
                return False
            self._sleep_interruptible(0.10)
        return False

    def _tap_ratio(self, x_ratio: float, y_ratio: float, pause: float = 1.0) -> None:
        _screenshot, width, height = self._capture_size()
        self.controller.tap(round(width * x_ratio), round(height * y_ratio))
        self._sleep_interruptible(pause)

    def _swipe_ratio(
        self,
        x_ratio: float,
        y_ratio: float,
        x2_ratio: float,
        y2_ratio: float,
        duration_ms: int = 420,
        pause: float = 0.6,
    ) -> None:
        _screenshot, width, height = self._capture_size()
        start = (round(width * x_ratio), round(height * y_ratio))
        end = (round(width * x2_ratio), round(height * y2_ratio))
        if hasattr(self.controller, "screenshot_to_client"):
            start = self.controller.screenshot_to_client(*start)
            end = self.controller.screenshot_to_client(*end)
        self.controller.swipe(*start, *end, duration_ms)
        self._sleep_interruptible(pause)

    def _find_daily_template(
        self,
        template_name: str,
        *,
        threshold: float = 0.72,
        region: tuple[int, int, int, int] | None = None,
        template_crop: tuple[int, int, int, int] | None = None,
        scales: list[float] | None = None,
        screenshot: Path | None = None,
    ):
        target = screenshot or (APP_DIR / "_runtime_screenshot.png")
        if self._weekly_monitoring and template_crop is None:
            from weekly_clicks import weekly_template_crop
            template_crop = weekly_template_crop(template_name, self.matcher.templates_dir)
        if screenshot is None:
            self._capture_for_matching(target)
        best = None
        for scale in scales or self._fast_scales():
            try:
                candidate = self.matcher.find_fast(
                    target,
                    template_name,
                    threshold=-1.0,
                    scale=scale,
                    region=region,
                    template_crop=template_crop,
                )
            except Exception:
                continue
            if best is None or candidate.score > best.score:
                best = candidate
            # The controller's first scale is the measured window scale. Once it
            # already clears the threshold, scanning four nearby scales only adds
            # seconds without changing the decision.
            if candidate.score >= threshold:
                return candidate
        return best if best is not None and best.score >= threshold else None

    def _wait_for_daily_template(
        self,
        template_name: str,
        *,
        timeout: float,
        threshold: float = 0.72,
        region_ratio: tuple[float, float, float, float] | None = None,
    ):
        deadline = time.monotonic() + timeout
        screenshot = APP_DIR / "_runtime_screenshot.png"
        attempt = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            _path, width, height = self._capture_size(screenshot)
            region = None
            if region_ratio is not None:
                region = (
                    round(width * region_ratio[0]),
                    round(height * region_ratio[1]),
                    round(width * region_ratio[2]),
                    round(height * region_ratio[3]),
                )
            match = self._find_daily_template(
                template_name,
                threshold=threshold,
                region=region,
                # The controller already knows the exact window scale. Use the
                # wider scale sweep only occasionally as a compatibility fallback.
                scales=None if attempt % 5 == 4 else [self._fast_scales()[0]],
                screenshot=screenshot,
            )
            if match is not None:
                return match
            attempt += 1
            self._sleep_interruptible(0.12)
        if self.stop_event.is_set():
            raise RuntimeError("一键日常已停止。")
        raise RuntimeError(f"等待界面元素超时：{template_name}")

    def _click_daily_template(
        self,
        template_name: str,
        label: str,
        *,
        timeout: float = 10.0,
        threshold: float = 0.72,
        region_ratio: tuple[float, float, float, float] | None = None,
    ) -> None:
        match = self._wait_for_daily_template(
            template_name,
            timeout=timeout,
            threshold=threshold,
            region_ratio=region_ratio,
        )
        self.log(f"    已识别{label}，相似度 {match.score:.3f}。")
        self.controller.tap(*match.center)
        self._sleep_interruptible(0.18)

    def _click_optional_daily_template(
        self,
        template_name: str,
        label: str,
        *,
        timeout: float = 3.0,
        threshold: float = 0.72,
    ) -> bool:
        try:
            self._click_daily_template(
                template_name,
                label,
                timeout=timeout,
                threshold=threshold,
            )
            return True
        except RuntimeError:
            return False

    def _open_terminal_destination(
        self,
        label: str,
        x_ratio: float,
        y_ratio: float,
        *,
        require_transition: bool = False,
    ) -> None:
        """Open the terminal from the overworld before entering a daily page."""
        self._wait_for_overworld_hud(minimum_wait=1.2 if require_transition else 0.0)
        self.log(f"    大世界按 Esc 打开终端，进入{label}。")
        self.controller.press_key("ESC", 70)
        self._sleep_interruptible(0.35)
        self._tap_ratio(x_ratio, y_ratio, 0.45)

    @staticmethod
    def _overworld_hud_ready(screenshot: Path) -> bool:
        """Recognize the normal game HUD and reject black/loading frames."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]

        def bright_ratio(box: tuple[float, float, float, float]) -> float:
            left, top, right, bottom = box
            crop = image[
                round(height * top):round(height * bottom),
                round(width * left):round(width * right),
            ]
            if crop.size == 0:
                return 0.0
            bright = (crop[:, :, 0] > 205) & (crop[:, :, 1] > 205) & (crop[:, :, 2] > 205)
            return float(bright.mean())

        # Normal overworld HUD simultaneously has top-right menu icons, the party
        # portraits on the right and action icons at the bottom-right.
        return (
            bright_ratio((0.70, 0.025, 0.985, 0.18)) >= 0.012
            and bright_ratio((0.86, 0.16, 0.985, 0.64)) >= 0.008
            and bright_ratio((0.72, 0.80, 0.985, 0.985)) >= 0.010
        )

    def _wait_for_overworld_hud(self, timeout: float = 25.0, minimum_wait: float = 0.0) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        started = time.monotonic()
        deadline = time.monotonic() + timeout
        confirmations = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._overworld_hud_ready(screenshot):
                confirmations += 1
                if confirmations >= 2 and time.monotonic() - started >= minimum_wait:
                    self.log("    已确认回到大世界。")
                    return
            else:
                confirmations = 0
            self._sleep_interruptible(0.22)
        if self.stop_event.is_set():
            raise RuntimeError("一键日常已停止。")
        raise RuntimeError("退出副本后未确认回到大世界，已停止以避免在加载界面误按 Esc。")

    @staticmethod
    def _sola_guide_page_ready(screenshot: Path) -> bool:
        """Require the stable Sola Guide chrome before classifying its current page."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        close_button = image[
            round(height * 0.02):round(height * 0.13),
            round(width * 0.92):round(width * 0.98),
        ]
        if close_button.size == 0:
            return False
        return float((close_button.min(axis=2) > 180).mean()) > 0.025

    @staticmethod
    def _daily_activity_page_present(screenshot: Path) -> bool:
        """The activity page is dominated by its large pale task rows."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        task_rows = image[
            round(height * 0.23):round(height * 0.80),
            round(width * 0.10):round(width * 0.96),
        ]
        if task_rows.size == 0:
            return False
        return float((task_rows.min(axis=2) > 170).mean()) > 0.45

    @staticmethod
    def _weekly_travel_page_present(screenshot: Path) -> bool:
        """Require the selected tab's text, not a pale training-target card."""
        return WeeklyRewardsVision(TEMPLATES_DIR / "weekly").weekly_page(screenshot)

    @staticmethod
    def _guide_material_page_present(screenshot: Path) -> bool:
        """Identify the normal material page reached after guide rewards are done."""
        with Image.open(screenshot) as source:
            width, height = source.size
        if abs(width / height - 16 / 9) > 0.04:
            return False
        try:
            TemplateMatcher(TEMPLATES_DIR / "daily").find_fast(
                screenshot, "guide_material_title.png", threshold=0.82, scale=width / 1920,
                region=(round(width * 0.05), round(height * 0.03),
                        round(width * 0.16), round(height * 0.11)),
            )
            return True
        except (RuntimeError, FileNotFoundError):
            return False

    def _daily_activity_still_pending(self, timeout: float = 6.0) -> bool:
        """Confirm the activity page and a counter at or above the daily target."""
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + timeout
        confirmations = 0
        last_state: tuple[bool,bool] | None = None
        self._daily_activity_confirmed_full = False
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if not self._sola_guide_page_ready(screenshot):
                confirmations = 0
                self._sleep_interruptible(0.15)
                continue
            page = self._daily_activity_page_present(screenshot)
            full = page and self._daily_activity_score_full(screenshot)
            state = (page,full)
            confirmations = confirmations + 1 if state == last_state else 1
            last_state = state
            if confirmations >= 2:
                self._daily_activity_confirmed_full = bool(full)
                return page and not full
            self._sleep_interruptible(0.15)
        raise RuntimeError("进入索拉指南后未能确认当前页面，已停止以避免误打无音区。")

    def _open_daily_tacet_field(self, zone_template: str) -> bool:
        self.log("    打开索拉指南 → 素材获取 → 无音清剿。")
        self._open_terminal_destination("索拉指南", 0.515, 0.671)
        if not self._daily_activity_still_pending():
            screenshot = APP_DIR / "_runtime_screenshot.png"
            if getattr(self,'_daily_activity_confirmed_full',False):
                self.log('    当前活跃度已达到100（包含150等更高分数），无需再刷无音区。')
                return False
            if self._weekly_travel_page_present(screenshot):
                self.log("    索拉指南自动进入周度游历，今日日常已完成。")
                return False
            # The guide may reopen on its previously selected material page.
            # That page is not evidence that the daily activity is complete.
            self.log("    索拉指南未停留在活跃度页，尝试切回左侧活跃度入口。")
            self._tap_ratio(0.04, 0.18, 0.45)
            if not self._daily_activity_still_pending():
                if getattr(self,'_daily_activity_confirmed_full',False):
                    self.log('    已确认活跃度达到100，转入奖励领取。')
                    return False
                if self._weekly_travel_page_present(screenshot):
                    self.log("    活跃度入口已自动跳转周度游历，今日日常已完成。")
                    return False
                raise RuntimeError("索拉指南未显示活跃度或周度游历页面，已停止以避免跳过日常。")
        self._click_daily_template(
            "guide_battle_tab.png",
            "索拉指南左侧战斗按钮",
            timeout=8.0,
            threshold=0.78,
            region_ratio=(0.015, 0.10, 0.095, 0.88),
        )
        self._sleep_interruptible(1.0)
        self._select_daily_tacet_section()

        screenshot = APP_DIR / "_runtime_screenshot.png"
        found = None
        numbered_huangshi = self.daily_zone_name in {
            "荒石高地无音区 I",
            "荒石高地无音区 II",
        }
        zone_threshold = 0.97 if numbered_huangshi else 0.90
        zone_crop = (6, 18, 304, 64) if numbered_huangshi else (6, 18, 190, 64)
        for page_index in range(32):
            _path, width, height = self._capture_size(screenshot)
            if zone_template in DAILY_ZONE_BUTTON_Y_OFFSETS:
                result = self._find_new_daily_zone(screenshot, zone_template)
                found = result[0] if result else None
                if found is None and page_index == 0:
                    wx, wy = round(width*.91), round(height*.60)
                    if hasattr(self.controller, 'screenshot_to_client'):
                        wx, wy = self.controller.screenshot_to_client(wx, wy)
                    self.controller.wheel_at(wx, wy, 7200)
                    self._sleep_interruptible(.25)
                    continue
            else:
                found = self._find_daily_template(
                zone_template,
                threshold=zone_threshold,
                region=(round(width * 0.34), round(height * 0.12), round(width * 0.98), round(height * 0.92)),
                template_crop=zone_crop,
                scales=[self._fast_scales()[0]],
                screenshot=screenshot,
            )
            if found is not None:
                if zone_template in DAILY_ZONE_BUTTON_Y_OFFSETS:
                    _title, button = result
                    if button is None:
                        self.log(f"    已看到“{self.daily_zone_name}”，同行按钮尚未完整可点，小幅滚动后重新识别。")
                        wx, wy = round(width*.91), round(height*.60)
                        if hasattr(self.controller, 'screenshot_to_client'):
                            wx, wy = self.controller.screenshot_to_client(wx, wy)
                        self.controller.wheel_at(wx, wy, -120)
                        self._sleep_interruptible(.25)
                        continue
                    self.log(f"    已识别“{self.daily_zone_name}”及同一行前往按钮，点击 {button.center}。")
                    self.controller.tap(*button.center)
                    self._sleep_interruptible(3.0)
                    break
                row_y = found.center[1] + round(DAILY_ZONE_BUTTON_Y_OFFSETS.get(zone_template, 0) * self._fast_scales()[0])
                if not self._daily_row_button_ready(screenshot, row_y):
                    wheel_x, wheel_y = round(width * 0.91), round(height * 0.60)
                    if hasattr(self.controller, "screenshot_to_client"):
                        wheel_x, wheel_y = self.controller.screenshot_to_client(wheel_x, wheel_y)
                    self.log(f"    已看到“{self.daily_zone_name}”，等待同一行按钮完整出现。")
                    if row_y > round(height * 0.68):
                        self.controller.wheel_at(wheel_x, wheel_y, -360)
                    self._sleep_interruptible(0.38)
                    found = None
                    continue
                button_x = round(width * 0.895)
                self._sleep_interruptible(0.32)
                self.log(
                    f"    精确找到“{self.daily_zone_name}”（第{page_index + 1}屏，相似度 {found.score:.3f}），"
                    "点击同一行的直接挑战/前往。"
                )
                self.controller.tap(button_x, row_y)
                self._sleep_interruptible(3.0)
                break
            wheel_x, wheel_y = round(width * 0.91), round(height * 0.60)
            if hasattr(self.controller, "screenshot_to_client"):
                wheel_x, wheel_y = self.controller.screenshot_to_client(wheel_x, wheel_y)
            self.controller.wheel_at(wheel_x, wheel_y, -720)
            self._sleep_interruptible(0.28)
        if found is None:
            raise RuntimeError(f"无音清剿列表中没有找到“{self.daily_zone_name}”。")
        self.log("    队伍界面点击“开启挑战”，不修改队伍。")
        self._tap_ratio(0.86, 0.92, 5.0)
        return True

    @staticmethod
    def _guide_tacet_section_selected(screenshot: Path, row_y: int) -> bool:
        """The selected sidebar row is pale; other material rows are dark."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        top = max(0, row_y - round(height * 0.03))
        bottom = min(height, row_y + round(height * 0.03))
        row = image[top:bottom, round(width * 0.105):round(width * 0.34)]
        return bool(row.size and float((row.min(axis=2) > 170).mean()) > 0.5)

    def _select_daily_tacet_section(self) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        for attempt in range(3):
            _path, width, height = self._capture_size(screenshot)
            if self._guide_tacet_section_selected(screenshot, round(height * 0.73)):
                self.log("    已确认战斗分类中的“无音清剿”处于选中状态。")
                return
            match = self._find_daily_template(
                "guide_tacet_section.png",
                threshold=0.72,
                region=(round(width * 0.10), round(height * 0.58),
                        round(width * 0.36), round(height * 0.88)),
                scales=[self._fast_scales()[0]],
                screenshot=screenshot,
            )
            if match is None:
                self._sleep_interruptible(0.4)
                continue
            # Click the row center, below the label. Its old hardcoded y=0.695
            # landed on the upper edge and could leave the wrong category open.
            click_y = min(height - 1, match.center[1] + round(height * 0.015))
            self.log(f"    已找到“无音清剿”子菜单（相似度 {match.score:.3f}），点击并复核选中状态。")
            self._tap_ratio(0.22, click_y / height, 0.65)
            self._capture_for_matching(screenshot)
            if self._guide_tacet_section_selected(screenshot, click_y):
                return
            self._sleep_interruptible(0.3)
        raise RuntimeError("战斗分类中未能选中“无音清剿”，已停止以避免点击错误副本。")

    def _find_new_daily_zone(self, screenshot: Path, template: str):
        with Image.open(screenshot) as source:
            width, height = source.size
        base = self._fast_scales()[0]
        region = (round(width*.10), round(height*.08), round(width*.98), round(height*.94))
        native = template.replace('.png', '_native.png')
        best_title = None
        # Keep the original 37px reference as well as the older 24px variant.
        # A cropped screenshot's font size is not determined by game width alone.
        for factor in (1., .8, 1.15, .65, 1.3, 1.5):
            for name, crop, reference in ((template, (0, 0, 82, 29), 24.),
                                          (native, (0, 0, 127, 45), 37.)):
                scale = base*factor
                title = self._find_daily_template(name, threshold=.85, region=region,
                                                  template_crop=crop, scales=[scale], screenshot=screenshot)
                if title is None:
                    continue
                if best_title is None or title.score > best_title.score:
                    best_title = title
                predicted_y = title.center[1] + round(57*reference/37*scale)
                row_region = (round(width*.58), max(0, predicted_y-round(38*scale)),
                              round(width*.98), min(height, predicted_y+round(38*scale)))
                for button_name, button_reference in (('zone_go_native.png', 37.),
                                                       ('zone_direct_challenge.png', 24.)):
                    button = self._find_daily_template(button_name, threshold=.82,
                                                       region=row_region, scales=[scale*reference/button_reference],
                                                       screenshot=screenshot)
                    if button is not None and self._daily_row_button_ready(screenshot, button.center[1], center_x=button.center[0]):
                        return title, button
        return (best_title, None) if best_title is not None else None

    @staticmethod
    def _daily_row_button_ready(screenshot: Path, row_y: int, *, center_x: int | None = None) -> bool:
        """Require the dark challenge button to be visible, not hidden by the footer."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        top = max(0, int(row_y) - round(height * 0.035))
        bottom = min(height, int(row_y) + round(height * 0.035))
        left, right = round(width * 0.82), round(width * 0.96)
        if center_x is not None:
            left, right = max(0, center_x-round(width*.065)), min(width, center_x+round(width*.065))
        region = image[top:bottom, left:right]
        if region.size == 0:
            return False
        dark = region.max(axis=2) < 75
        lines = np.flatnonzero(dark.mean(axis=1) >= .30)
        if not len(lines):
            return False
        runs = np.split(lines, np.where(np.diff(lines) != 1)[0]+1)
        minimum = max(12, round(height*.03))
        local_y = int(row_y)-top
        return any(len(run) >= minimum and run[0] <= local_y <= run[-1] for run in runs)

    def _daily_battle_task_present(self, screenshot: Path) -> bool:
        with Image.open(screenshot) as captured:
            width, height = captured.size
        return self._find_daily_template(
            "battle_task_text.png",
            threshold=0.67,
            region=(0, round(height * 0.15), round(width * 0.43), round(height * 0.42)),
            scales=[self._fast_scales()[0]],
            screenshot=screenshot,
        ) is not None

    def _select_daily_slot_after_loading(self, screenshot: Path, slot: int = 1) -> None:
        """Wait for the battle HUD, then ensure the first configured character is active."""
        deadline = time.monotonic() + 15.0
        hud_ready = False
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            self._capture_for_matching(screenshot)
            if self._daily_battle_task_present(screenshot):
                hud_ready = True
                break
            self._sleep_interruptible(0.15)
        self.controller.press_key(str(slot), 65)
        self._sleep_interruptible(0.08)
        if hud_ready:
            self.log(f"    战斗界面已加载，按 {slot} 确保当前角色为{SLOT_NAMES[slot]}。")
        else:
            self.log(f"    等待战斗界面超时，仍按 {slot} 强制切换至{SLOT_NAMES[slot]}。")

    def _run_daily_battle(
        self,
        step: Step,
        skill_key: str,
        ultimate_key: str,
        cycle_index: int,
    ) -> None:
        started = time.monotonic()
        deadline = started + max(180.0, step.timeout)
        modules = self.rotation_presets.get("daily", self.rotation_modules)
        first_slot = self._rotation_first_slot(modules, "daily")
        self._rotation_slot = first_slot
        self._rotation_battle_finished = False
        self._rotation_end_check = self._daily_reward_stage_present
        self._combat_animation_until = 0.
        self._rotation_continuous_started = False
        last_task_check = 0.0
        task_seen = False
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._select_daily_slot_after_loading(screenshot, first_slot)
        if self.stop_event.is_set():
            return
        self.controller.middle_click()
        self.log(
            f"    第{cycle_index}轮：中键锁定后，"
            f"按日常预设执行 {len(modules)} 个战斗模块。"
        )

        attack_enabled = threading.Event()
        attack_lock = threading.Lock()
        rotation = RotationClock(modules, time.monotonic(), self.MAIN_ATTACK_CLICK_INTERVAL,
                                 self.rotation_times.get("daily"), background_idle=True,
                                 slot_order=self.rotation_orders.get("daily"))
        idle_worker = IdleAttackWorker(self.controller, self.stop_event, attack_lock,
                                       attack_interval=self.MAIN_ATTACK_CLICK_INTERVAL,
                                       heavy_hold_ms=self.HEAVY_ATTACK_HOLD_MS,
                                       on_error=lambda exc: self.log(f"    空闲普攻失败：{exc}"))
        self._rotation_idle_worker = idle_worker
        monitor = None
        try:
            def inspect():
                self._capture_for_matching(screenshot)
                reward = self._daily_reward_stage_present(screenshot)
                return reward, False if reward else self._daily_battle_task_present(screenshot)

            monitor = BattleMonitor(inspect, inspect(), self.stop_event)
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return
                now = time.monotonic()
                checked = monitor.poll()
                if checked is not None:
                    reward, present = checked[0]
                    if reward:
                        idle_worker.pause()
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        self.controller.release_keys()
                        self.log("    已识别到领取奖励提示，停止战斗并进入奖励搜索。")
                        return
                    last_task_check = time.monotonic()
                    if present:
                        task_seen = True
                    elif time.monotonic() < self._combat_animation_until:
                        pass
                    elif task_seen:
                        idle_worker.pause()
                        monitor.pause()
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        self.controller.release_keys()
                        if self._confirm_daily_battle_finished(screenshot):
                            self.log("    左侧清理目标文字快速复核后仍消失，进入奖励获取阶段。")
                            return
                        monitor.resume()
                        last_task_check = time.monotonic()
                        continue
                elif now - last_task_check >= self.DAILY_BATTLE_END_CHECK_INTERVAL:
                    monitor.request()
                action = rotation.next_action(time.monotonic())
                if not self._run_rotation_action(action, rotation, skill_key, ultimate_key,
                                                 attack_enabled, attack_lock, daily=True,
                                                 task_seen=task_seen, screenshot=screenshot):
                    return
                self._sleep_interruptible(0.025)
            if not task_seen:
                raise RuntimeError("没有识别到无音区清理目标文字，请确认已进入无音区挑战。")
            raise RuntimeError("无音区单轮战斗达到安全时限，已自动停止。")
        finally:
            idle_worker.close()
            self._rotation_idle_worker = None
            self._rotation_end_check = None
            attack_enabled.clear()
            try:
                self.controller.release_keys()
            finally:
                if monitor is not None:
                    monitor.close()
            if monitor is not None and monitor.error is not None:
                raise RuntimeError(f"战斗画面检查失败：{monitor.error}") from monitor.error
            if idle_worker.error is not None:
                raise RuntimeError(f"空闲普攻失败：{idle_worker.error}") from idle_worker.error

    @classmethod
    def _ultimate_indicator_ready(cls, screenshot: Path) -> bool:
        """Classify the lower-right ultimate icon without matching character art."""
        with Image.open(screenshot) as source:
            frame = np.asarray(source.convert("RGB"))
        height, width = frame.shape[:2]
        left, top, right, bottom = cls.ULTIMATE_INDICATOR_REGION
        crop = frame[
            round(height * top):round(height * bottom),
            round(width * left):round(width * right),
        ]
        return cls._ultimate_indicator_crop_ready(crop, expected_radius=height * 0.034)

    @classmethod
    def _ultimate_indicator_crop_ready(
        cls,
        crop: np.ndarray,
        expected_radius: float | None = None,
    ) -> bool:
        """Recognize a charged colorful ring while rejecting gray/partial/cooldown rings."""
        image = np.asarray(crop, dtype=np.float32)
        if image.ndim != 3 or image.shape[2] < 3:
            return False
        image = image[:, :, :3]
        height, width = image.shape[:2]
        minimum = min(height, width)
        if minimum < 40:
            return False

        maximum = image.max(axis=2)
        minimum_channel = image.min(axis=2)
        saturation = (maximum - minimum_channel) / np.maximum(maximum, 1.0)
        brightness = maximum / 255.0
        angles = np.linspace(0.0, 2.0 * np.pi, 48, endpoint=False)
        step = max(2, round(minimum / 40))
        best: tuple[float, int, int, int] | None = None

        if expected_radius is None:
            radius_start = max(12, round(minimum * 0.22))
            radius_stop = max(radius_start + 1, round(minimum * 0.43))
        else:
            radius_start = max(12, round(expected_radius * 0.72))
            radius_stop = max(radius_start + 1, round(expected_radius * 1.28))
        for radius in range(radius_start, radius_stop + 1, step):
            for center_y in range(round(height * 0.15), round(height * 0.62) + 1, step):
                for center_x in range(round(width * 0.25), round(width * 0.75) + 1, step):
                    ring_values = []
                    for radius_factor in (0.86, 1.0, 1.14):
                        xs = np.clip(
                            np.rint(center_x + np.cos(angles) * radius * radius_factor).astype(int),
                            0,
                            width - 1,
                        )
                        ys = np.clip(
                            np.rint(center_y + np.sin(angles) * radius * radius_factor).astype(int),
                            0,
                            height - 1,
                        )
                        ring_values.append(brightness[ys, xs])
                    sampled_brightness = np.concatenate(ring_values)
                    bright_coverage = float((sampled_brightness > 0.55).mean())
                    glyph_top = min(height, center_y + radius + 1)
                    glyph_bottom = min(height, center_y + radius + round(radius * 0.8))
                    glyph_left = max(0, center_x - round(radius * 0.3))
                    glyph_right = min(width, center_x + round(radius * 0.3))
                    glyph = brightness[glyph_top:glyph_bottom, glyph_left:glyph_right]
                    glyph_coverage = float((glyph > 0.75).mean()) if glyph.size else 0.0
                    score = (
                        bright_coverage
                        + 0.35 * glyph_coverage
                        + 0.20 * float(sampled_brightness.mean())
                    )
                    if best is None or score > best[0]:
                        best = (score, center_x, center_y, radius)

        if best is None:
            return False
        _score, center_x, center_y, radius = best
        yy, xx = np.ogrid[:height, :width]
        distance = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)
        ring = (distance > radius * 0.78) & (distance < radius * 1.18)
        if not ring.any():
            return False
        color_coverage = float(
            ((brightness > 0.50) & (saturation > 0.25) & ring).sum() / ring.sum()
        )
        mean_saturation = float(saturation[ring].mean())
        mean_brightness = float(brightness[ring].mean())
        return (
            color_coverage >= cls.ULTIMATE_RING_MIN_COLOR_COVERAGE
            and mean_saturation >= cls.ULTIMATE_RING_MIN_SATURATION
            and mean_brightness >= cls.ULTIMATE_RING_MIN_BRIGHTNESS
        )

    def _find_daily_reward_prompt(self, screenshot: Path):
        with Image.open(screenshot) as captured:
            width, height = captured.size
        return self._find_daily_template(
            "reward_prompt.png",
            threshold=0.72,
            region=(
                round(width * 0.38),
                round(height * 0.35),
                round(width * 0.96),
                round(height * 0.80),
            ),
            scales=[self._fast_scales()[0]],
            screenshot=screenshot,
        )

    def _daily_reward_stage_present(self, screenshot: Path) -> bool:
        # White enemies and skill effects are not evidence that combat ended.
        # Colour navigation is only used after the battle-end confirmation.
        return self._find_daily_reward_prompt(screenshot) is not None

    @staticmethod
    def _daily_reward_orb_location(screenshot: Path) -> tuple[int | None, int | None, float]:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        # Only inspect the 3D scene above the character. This excludes portraits,
        # skill icons and most text HUD elements that can otherwise look white.
        top, bottom = round(height * 0.13), round(height * 0.52)
        left, right = round(width * 0.08), round(width * 0.84)
        region = image[top:bottom, left:right]
        red = region[:, :, 0].astype(np.int16)
        green = region[:, :, 1].astype(np.int16)
        blue = region[:, :, 2].astype(np.int16)
        # Reward orb has a dense white core. The blue-black exit portal does not.
        white = (red > 218) & (green > 218) & (blue > 225) & ((np.maximum.reduce((red, green, blue)) - np.minimum.reduce((red, green, blue))) < 48)
        if not white.any():
            return None, None, 0.0
        block = 28
        usable_h = (white.shape[0] // block) * block
        usable_w = (white.shape[1] // block) * block
        if usable_h < block or usable_w < block:
            return None, None, 0.0
        counts = white[:usable_h, :usable_w].reshape(usable_h // block, block, usable_w // block, block).sum(axis=(1, 3))
        cell_y, cell_x = np.unravel_index(np.argmax(counts), counts.shape)
        density = float(counts[cell_y, cell_x] / (block * block))
        if density <= DAILY_REWARD_ORB_MIN_CONFIDENCE:
            return None, None, density
        return left + cell_x * block + block // 2, top + cell_y * block + block // 2, density

    def _collect_daily_reward(self, cycle_index: int) -> bool:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + 75.0
        previous_forward_confidence: float | None = None
        sweep = None
        approaching = False
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            prompt = self._find_daily_reward_prompt(screenshot)
            target_x, _target_y, density = self._daily_reward_orb_location(screenshot)
            # A white object must never override evidence of ongoing combat.
            if (
                prompt is None
                and self._daily_battle_task_present(screenshot)
            ):
                self.controller.release_keys()
                self.log("    奖励搜索时发现左侧清理目标文字仍在，判定战斗尚未结束，继续攻击。")
                return False
            with Image.open(screenshot) as captured:
                width, height = captured.size
                scan_image = captured.copy()
            if self.stop_event.is_set():
                break
            if prompt is not None:
                self.controller.release_keys()
                self.controller.press_key("F", 100)
                self.log(f"    第{cycle_index}轮：识别到“领取奖励”，已按 F。")
                self._sleep_interruptible(0.2)
                self._claim_daily_double_reward(cycle_index)
                return True
            valid = target_x is not None and density > DAILY_REWARD_ORB_MIN_CONFIDENCE
            stalled = self._daily_reward_movement_stalled(previous_forward_confidence, density)
            if valid and density > ORB_DIRECT_CONFIDENCE:
                approaching, sweep = True, None
                self.log(f"    光球置信度 {density:.2f} 超过0.80，直接前往。")
            elif not valid or stalled:
                approaching = False
            if not approaching:
                if sweep is None:
                    sweep = OrbDirectionSweep()
                    self.log("    开始水平转满一圈，记录各方向光球置信度；超过0.80时直接前往。")
                sweep.observe(scan_image, target_x, density)
                previous_forward_confidence = None
                if sweep.complete:
                    if sweep.best is not None:
                        self.log(f"    已转满一圈，选择最高置信度 {sweep.best.confidence:.2f} 的方向。")
                        self._turn_daily_reward_camera(sweep.return_delta())
                        approaching = True
                    else:
                        self.log("    已转满一圈，未找到有效光球，重新扫描。")
                    sweep = None
                    continue  # Fresh screenshot at the selected direction before moving.
                self.controller.move_mouse_relative(ORB_SCAN_STEP, 0)
                sweep.advance(ORB_SCAN_STEP)
            else:
                offset = target_x - width * 0.5
                if abs(offset) > width * 0.05:
                    self.controller.move_mouse_relative(int(max(-300, min(300, offset * 0.40))), 0)
                self.controller.press_keys(("W",), 500)
                self.log(f"    已定位白色奖励光球（核心密度 {density:.2f}），正在靠近。")
                previous_forward_confidence = density
            self._sleep_interruptible(0.22)
        raise RuntimeError("奖励阶段未找到“领取奖励”提示，已停止以避免误操作。")

    def _turn_daily_reward_camera(self, delta: int) -> None:
        while delta and not self.stop_event.is_set():
            step = max(-ORB_SCAN_STEP, min(ORB_SCAN_STEP, delta))
            self.controller.move_mouse_relative(step, 0)
            delta -= step
            self._sleep_interruptible(.12)

    @staticmethod
    def _daily_reward_movement_stalled(previous: float | None, current: float) -> bool:
        return previous is not None and current <= previous

    def _claim_daily_double_reward(self, cycle_index: int) -> None:
        self._click_daily_template(
            "double_claim.png",
            "双倍领取",
            timeout=12.0,
            threshold=0.68,
            region_ratio=(0.50, 0.54, 0.80, 0.75),
        )
        state = self._wait_daily_claim_state(8.0)
        if state == "success":
            return
        if state != "refill":
            raise RuntimeError("点击双倍领取后没有进入奖励或体力补充界面。")
        self.log("    体力不足：只允许使用结晶单质或结晶溶剂，绝不选择星声。")
        # A successful resource-consumption toast does not prove that the total
        # stamina is sufficient. Retry the claim and, if the chooser reopens,
        # continue with the next safe resource (green -> yellow).
        for refill_pass in range(2):
            if not self._safe_refill_daily_stamina():
                raise RuntimeError("结晶单质和结晶溶剂均不可用，已停止；不会使用星声兑换体力。")
            self._tap_ratio(0.14, 0.84, 0.35)  # 安全空白，不触碰物品卡。
            self._click_daily_template(
                "double_claim.png",
                "补充体力后的双倍领取",
                timeout=10.0,
                threshold=0.68,
                region_ratio=(0.50, 0.54, 0.80, 0.75),
            )
            state = self._wait_daily_claim_state(10.0)
            if state == "success":
                return
            if state == "refill" and refill_pass == 0:
                self.log("    已使用一种补充材料但体力仍不足，继续选择下一种安全材料。")
                continue
            break
        raise RuntimeError(f"第{cycle_index}轮使用绿色与黄色材料后体力仍不足，已停止且不会使用星声。")

    def _wait_daily_claim_state(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        screenshot = APP_DIR / "_runtime_screenshot.png"
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            with Image.open(screenshot) as captured:
                width, height = captured.size
            exact_scale = [self._fast_scales()[0]]
            if self._find_daily_template(
                "challenge_success.png",
                threshold=0.66,
                region=(round(width * 0.31), round(height * 0.20), round(width * 0.69), round(height * 0.43)),
                scales=exact_scale,
                screenshot=screenshot,
            ):
                return "success"
            if self._find_daily_template(
                "refill_dialog.png",
                threshold=0.62,
                region=(round(width * 0.14), round(height * 0.16), round(width * 0.48), round(height * 0.33)),
                scales=exact_scale,
                screenshot=screenshot,
            ):
                return "refill"
            self._sleep_interruptible(0.08)
        return ""

    def _safe_refill_daily_stamina(self) -> bool:
        # Left and middle cards are the only permitted resources. The star card is
        # at the right and is never selected, even as a fallback.
        screenshot = APP_DIR / "_runtime_screenshot.png"
        resources = [("结晶单质", 0.403), ("结晶溶剂", 0.505)]
        if self._daily_monomer_empty_after_settle(screenshot):
            self.log("    结晶单质数量为0，跳过绿色卡片，直接使用结晶溶剂。")
            resources = resources[1:]
        for label, x_ratio in resources:
            self.log(f"    尝试使用{label}，数量由游戏自动计算。")
            self._tap_ratio(x_ratio, 0.455, 0.25)
            # First confirmation enters the exchange screen; the game has already
            # calculated the required amount, so never touch its slider or MAX.
            self._tap_ratio(0.695, 0.745, 0.65)
            self._tap_ratio(0.695, 0.745, 0.75)
            state = self._wait_daily_refill_result()
            if state == "success":
                self.log(f"    {label}补充成功。")
                return True
            if state == "still_short":
                if label == "结晶单质":
                    self.log("    使用结晶单质后仍不足，继续改用结晶溶剂。")
                continue
            # An unknown screen must not be treated as a successful refill. Doing
            # so could make the next click land on the forbidden star-currency card.
            self.log(f"    无法确认{label}补充结果，停止以避免误用星声。")
            return False
        self._tap_ratio(0.30, 0.745, 0.5)
        return False

    def _daily_monomer_empty_after_settle(self, screenshot: Path, timeout: float = 0.7) -> bool:
        """Wait briefly for the resource counts to finish appearing before deciding."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._daily_monomer_empty(screenshot):
                return True
            self._sleep_interruptible(0.10)
        return False

    @staticmethod
    def _daily_monomer_empty(screenshot: Path) -> bool:
        """Detect the red zero at the lower-right of the green resource card."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        crop = image[
            round(height * 0.46):round(height * 0.58),
            round(width * 0.400):round(width * 0.455),
        ]
        if crop.size == 0:
            return False
        red = crop[:, :, 0].astype(np.int16)
        green = crop[:, :, 1].astype(np.int16)
        blue = crop[:, :, 2].astype(np.int16)
        unavailable_red = (
            (red > 100)
            & (green < 125)
            & (blue < 125)
            & ((red - green) > 30)
            & ((red - blue) > 20)
        )
        return int(unavailable_red.sum()) >= 4

    @staticmethod
    def _daily_refill_chooser_present(screenshot: Path) -> bool:
        """Recognize the refill chooser geometrically when its title template shifts."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]

        def crop(box: tuple[float, float, float, float]) -> np.ndarray:
            left, top, right, bottom = box
            return image[
                round(height * top):round(height * bottom),
                round(width * left):round(width * right),
            ]

        panel = crop((0.17, 0.16, 0.83, 0.80))
        cards = crop((0.35, 0.34, 0.64, 0.59))
        buttons = crop((0.20, 0.68, 0.80, 0.79))
        if not panel.size or not cards.size or not buttons.size:
            return False
        bright_panel = float((panel.min(axis=2) > 205).mean())
        dark_cards = float((cards.max(axis=2) < 180).mean())
        dark_buttons = float((buttons.max(axis=2) < 100).mean())
        return bright_panel > 0.42 and dark_cards > 0.20 and dark_buttons > 0.22

    def _wait_daily_refill_result(self, timeout: float = 3.5) -> str:
        """Wait until refill succeeds or the refill chooser is visibly still open."""
        deadline = time.monotonic() + timeout
        screenshot = APP_DIR / "_runtime_screenshot.png"
        attempt = 0
        chooser_confirmations = 0
        success_confirmations = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            with Image.open(screenshot) as captured:
                width, height = captured.size
            scales = None if attempt == 3 else [self._fast_scales()[0]]
            # The title moves slightly when the game adds the "still insufficient"
            # banner. The chooser takes priority over the temporary "successfully
            # consumed" toast: the latter does not mean stamina is sufficient.
            chooser_visible = bool(self._find_daily_template(
                "refill_dialog.png",
                threshold=0.56,
                region=(round(width * 0.14), round(height * 0.16), round(width * 0.48), round(height * 0.33)),
                scales=scales,
                screenshot=screenshot,
            )) or (attempt >= 2 and self._daily_refill_chooser_present(screenshot))
            chooser_confirmations = chooser_confirmations + 1 if chooser_visible else 0
            if chooser_confirmations >= 2:
                return "still_short"
            success_visible = bool(self._find_daily_template(
                "refill_success.png",
                threshold=0.60,
                region=(round(width * 0.30), round(height * 0.16), round(width * 0.70), round(height * 0.34)),
                scales=scales,
                screenshot=screenshot,
            ))
            success_confirmations = success_confirmations + 1 if success_visible and not chooser_visible else 0
            if success_confirmations >= 2:
                return "success"
            attempt += 1
            self._sleep_interruptible(0.08)
        return ""

    def _wait_for_daily_success(self, cycle_index: int) -> None:
        match = self._wait_for_daily_template(
            "challenge_success.png",
            timeout=15.0,
            threshold=0.64,
            region_ratio=(0.31, 0.20, 0.69, 0.43),
        )
        self.log(f"    第{cycle_index}轮挑战成功，相似度 {match.score:.3f}。")

    @staticmethod
    def _yellow_claim_rows(screenshot: Path) -> list[int]:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        left, right = round(width * 0.78), round(width * 0.97)
        top, bottom = round(height * 0.14), round(height * 0.84)
        region = image[top:bottom, left:right]
        red = region[:, :, 0].astype(np.int16)
        green = region[:, :, 1].astype(np.int16)
        blue = region[:, :, 2].astype(np.int16)
        yellow = (red > 225) & (green > 215) & (blue < 235) & ((red - blue) > 25)
        row_counts = yellow.sum(axis=1)
        active = np.flatnonzero(row_counts > max(12, region.shape[1] * 0.15))
        if not len(active):
            return []
        # Pale yellow buttons contain dark text and patterned highlights. Join
        # those gaps so one button produces one centre, not several edge clicks.
        groups = np.split(active, np.flatnonzero(np.diff(active) > max(4, round(height*.015)))+1)
        return [top+int((group[0]+group[-1])//2) for group in groups
                if group[-1]-group[0]+1 >= max(12, round(height*.018))]

    def _daily_activity_score_full(self, screenshot: Path) -> bool:
        from daily_activity import activity_counter_full
        return activity_counter_full(screenshot, TEMPLATES_DIR/'daily'/'activity_full.png')

    def _wait_daily_reward_page(self, template: str, label: str, *, dismiss_overlay: bool = False) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic()+8
        confirmations = 0
        while time.monotonic() < deadline and not self.stop_event.is_set():
            _path, width, height = self._capture_size(screenshot)
            title = self._find_daily_template(template, threshold=.82, screenshot=screenshot,
                region=(round(width*.02), round(height*.025), round(width*.26), round(height*.13)))
            ready = title is not None and self._daily_activity_page_present(screenshot)
            confirmations = confirmations+1 if ready else 0
            if confirmations >= 2:
                return
            # Reward overlays can finish appearing after the blank-area click.
            # This spot is outside task buttons and milestone chests.
            if title is None and dismiss_overlay:
                self._dismiss_reward_overlay_safely()
            self._sleep_interruptible(.15)
        raise RuntimeError(f"未确认{label}页面已稳定显示，已停止以避免跳过领取。")

    def _dismiss_reward_overlay_safely(self) -> None:
        # Both the stamina exchange success and item reward overlays explicitly
        # allow a blank-area click. Bottom-left is outside every item card.
        self._tap_ratio(0.13, 0.86, 0.18)

    def _collect_daily_activity_rewards(self, *, already_open: bool = False) -> None:
        self.log('    直接领取当前活跃行迹页面的奖励。' if already_open else
                 "    返回大世界后，经终端进入索拉指南领取活跃度奖励；只点击黄色“领取”，不点击“前往”。")
        if not already_open:
            self._open_terminal_destination("索拉指南", 0.515, 0.671, require_transition=True)
        # The guide can remember a different category. Select activity explicitly
        # and wait for its title rather than treating an unpainted frame as empty.
        if not already_open:
            self._tap_ratio(.039, .174, .15)
        self._wait_daily_reward_page("activity_title.png", "活跃行迹")
        self.log("    已确认活跃行迹页面，先领取上方任务奖励。")
        screenshot = APP_DIR / "_runtime_screenshot.png"
        empty_frames = 0
        for _ in range(36):
            if self.stop_event.is_set():
                return
            self._capture_for_matching(screenshot)
            rows = self._yellow_claim_rows(screenshot)
            if not rows:
                empty_frames += 1
                if empty_frames >= 2:
                    break
                self._sleep_interruptible(.15)
                continue
            empty_frames = 0
            with Image.open(screenshot) as captured:
                width = captured.width
            self.controller.tap(round(width * 0.88), rows[0])
            self._sleep_interruptible(.35)
            self._dismiss_reward_overlay_safely()
            self._wait_daily_reward_page("activity_title.png", "活跃行迹", dismiss_overlay=True)
        else:
            raise RuntimeError("活跃度领取多次后仍未完成，已停止；不会提前点击100宝箱。")

        if self.stop_event.is_set():
            return
        # A completed daily route earns enough activity. Claim the final chest
        # after the task rewards, regardless of the rendered counter (100/120/
        # 140/160 or a missed digit); it must not block a successful route.
        self.log("    上方任务奖励已领取，直接领取100宝箱；不再按活跃度数字拦截，其余里程碑奖励由游戏一并领取。")
        self._tap_ratio(0.945, 0.868, 0.25)
        self._dismiss_reward_overlay_safely()
        self._tap_ratio(0.957, 0.058, 0.4)

    def _collect_daily_battlepass_rewards(self) -> None:
        self.log("    退出活跃指南后已在终端，直接进入先约电台；只领取免费内容，不点击购买或解锁寰宇频道。")
        self._tap_ratio(0.744, 0.257, 0.7)
        self._wait_daily_battlepass_tab(2)
        if self._click_optional_daily_template("one_click_claim.png", "电台任务一键领取", timeout=5.0, threshold=0.66):
            self._dismiss_reward_overlay_safely()
        self._wait_daily_battlepass_tab(1)
        if self._click_optional_daily_template("one_click_claim.png", "大众频道一键领取", timeout=5.0, threshold=0.66):
            self._dismiss_reward_overlay_safely()
        self._tap_ratio(0.957, 0.058, 0.8)

    def _daily_battlepass_tab_selected(self, screenshot: Path, tab: int) -> bool:
        with Image.open(screenshot) as source:
            width, height = source.size
            y = .174 if tab == 1 else .299
            icon = np.asarray(source.crop((round(width*.025), round(height*(y-.028)),
                                           round(width*.055), round(height*(y+.028)))).convert('RGB'))
        red, green, blue = (icon[:, :, i].astype(np.int16) for i in range(3))
        selected = (red > 150) & (green > 135) & (blue < green-25) & (red > blue+40)
        if float(selected.mean()) < .08:
            return False
        if tab == 2:
            return self._find_daily_template("battlepass_tasks.png", threshold=.82, screenshot=screenshot,
                region=(round(width*.015), round(height*.025), round(width*.25), round(height*.13))) is not None
        # Ensure the selected icon is the radio's reward channel, not a similarly
        # positioned guide icon. Its shape remains recognizable when highlighted.
        return self._find_daily_template("battlepass_rewards_tab.png", threshold=.72, screenshot=screenshot,
            region=(round(width*.02), round(height*.135), round(width*.06), round(height*.215))) is not None

    def _wait_daily_battlepass_tab(self, tab: int) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic()+8
        confirmations = 0
        next_click = 0.
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._daily_battlepass_tab_selected(screenshot, tab):
                confirmations += 1
                if confirmations >= 2:
                    self.log(f"    已确认先约电台左侧第{tab}个标签。")
                    return
            else:
                confirmations = 0
                if time.monotonic() >= next_click:
                    self._tap_ratio(.039, .174 if tab == 1 else .299, .15)
                    next_click = time.monotonic()+.6
            self._sleep_interruptible(.12)
        raise RuntimeError(f"未确认先约电台左侧第{tab}个标签已打开，已停止以避免跳过奖励。")

    @staticmethod
    def _weekly_travel_completed(screenshot: Path) -> bool:
        """Detect the check mark on the inactive weekly-travel tab."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        region = image[
            round(height * 0.151):round(height * 0.187),
            round(width * 0.385):round(width * 0.405),
        ]
        if region.size == 0:
            return False
        high = region.max(axis=2)
        low = region.min(axis=2)
        neutral_check = ((high - low) < 35) & (high > 110)
        return float(neutral_check.mean()) > 0.15

    @staticmethod
    def _weekly_skill_slot_empty(screenshot: Path) -> bool:
        """Detect the sparse cream plus sign shown by an empty blessing slot."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        slot = image[
            round(height * 0.735):round(height * 0.845),
            round(width * 0.445):round(width * 0.507),
        ]
        if slot.size == 0:
            return False
        red = slot[:, :, 0].astype(np.int16)
        green = slot[:, :, 1].astype(np.int16)
        blue = slot[:, :, 2].astype(np.int16)
        cream = (red > 220) & (green > 195) & (blue > 120) & ((red - green) < 45)
        density = float(cream.mean())
        widest_row = int(cream.sum(axis=1).max(initial=0)) / max(1, cream.shape[1])
        tallest_column = int(cream.sum(axis=0).max(initial=0)) / max(1, cream.shape[0])
        return 0.015 < density < 0.11 and widest_row > 0.25 and tallest_column > 0.25

    @staticmethod
    def _weekly_skill_equipped(screenshot: Path) -> bool:
        """Any known weekly slot without the explicit plus sign is equipped."""
        return not TaskRunner._weekly_skill_slot_empty(screenshot)

    def _ensure_weekly_skill_selected(self) -> None:
        """Use one shared empty-slot rule for standalone and daily-triggered weekly runs."""
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._capture_for_matching(screenshot)
        if self._weekly_skill_equipped(screenshot):
            self.log("    已装备幻梦祝福，保留当前技能，不重复打开选择界面。")
            return
        self.log("    检测到“＋ / 选择祝福”空槽，打开技能选择并固定选择第一个技能。")
        self._tap_ratio(0.496, 0.768, 0.18)
        self._wait_for_weekly_skill_dialog()
        self._tap_ratio(0.371, 0.505, 0.18)
        self._tap_ratio(0.826, 0.858, 0.55)
        self._wait_for_daily_template("menu1.png", timeout=8.0, threshold=WEEKLY_TEMPLATE_THRESHOLD)

    @staticmethod
    def _weekly_skill_dialog_present(screenshot: Path) -> bool:
        """Confirm that the four-card blessing selector is fully visible."""
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB")).astype(np.float32)
        height, width = image.shape[:2]
        title = image[
            round(height * 0.20):round(height * 0.32),
            round(width * 0.43):round(width * 0.82),
        ]
        body = image[
            round(height * 0.30):round(height * 0.78),
            round(width * 0.27):round(width * 0.97),
        ]
        if title.size == 0 or body.size == 0:
            return False
        green_title = (
            (title[:, :, 1] > 100)
            & (title[:, :, 1] > title[:, :, 0] * 1.03)
            & (title[:, :, 1] > title[:, :, 2] * 1.12)
        )
        bright_body = body.max(axis=2) > 190
        return float(green_title.mean()) > 0.30 and float(bright_body.mean()) > 0.65

    def _wait_for_weekly_skill_dialog(self, timeout: float = 5.0) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            if self._weekly_skill_dialog_present(screenshot):
                return
            self._sleep_interruptible(0.12)
        raise RuntimeError("点击祝福技能槽后未出现四技能选择界面，已停止以避免误点。")

    def _run_default_weekly_from_daily(self) -> None:
        """Reuse the established menu template chain for the 15-round reward run."""
        self._weekly_monitoring = True
        self.template_root = TEMPLATES_DIR
        self.matcher.templates_dir = TEMPLATES_DIR
        self.max_cycles = 15
        start_step = Step(
            action="tap_image",
            label="点击幻梦游园开始游戏",
            template="menu1.png",
            threshold=WEEKLY_TEMPLATE_THRESHOLD,
            timeout=12.0,
            offset_x=80,
            seconds=WEEKLY_CLICK_INTERVAL,
        )
        cycle_step = Step(
            action="tap_image_cycle",
            label="自动执行15轮幻梦游园",
            templates=self._numbered_templates("menu", 2, 99),
            loop=True,
            threshold=WEEKLY_TEMPLATE_THRESHOLD,
            timeout=1.0,
            seconds=WEEKLY_CLICK_INTERVAL,
        )
        self._run_weekly_dynamic(start_step, cycle_step)

    def _run_weekly_dynamic(self, start_step: Step, cycle_step: Step) -> None:
        from weekly_flow import run_weekly_flow
        run_weekly_flow(self, start_step, cycle_step, attempts=CYCLE_PROBE_ATTEMPTS,
                        nearby_attempts=CYCLE_NEIGHBOR_PROBE_ATTEMPTS)

    def _start_weekly_travel_from_selected_page(self) -> None:
        """Enter Dream Park from an already selected unfinished weekly page."""
        self._tap_ratio(0.247, 0.505, 0.8)
        self.template_root = TEMPLATES_DIR
        self.matcher.templates_dir = TEMPLATES_DIR
        self.log("    已进入周常，按当前页面接续周常拿满奖励（15轮）。")
        self._run_default_weekly_from_daily()

    def _continue_daily_from_open_guide_page(self) -> None:
        """After activity auto-skips, run weekly only when weekly is the selected page."""
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._capture_for_matching(screenshot)
        if not self._weekly_travel_page_present(screenshot):
            self.log("    索拉指南已自动跳过周度游历，判定本周周常也已完成。")
            self._tap_ratio(0.957, 0.058, 0.35)
            return
        self.log("    日常已完成，但周度游历仍未完成；进入幻梦游园继续执行周常。")
        self._start_weekly_travel_from_selected_page()

    def _continue_daily_into_weekly_travel(self) -> None:
        """Run weekly only when Sola Guide automatically selects its unfinished page."""
        self.log("    回到终端后再次进入索拉指南，检查周度游历。")
        self._tap_ratio(0.515, 0.671, 0.65)
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self._capture_for_matching(screenshot)
        if self._weekly_travel_page_present(screenshot):
            self.log("    索拉指南已选中未完成的周度游历，直接进入幻梦游园。")
            self._start_weekly_travel_from_selected_page()
            return
        if self._guide_material_page_present(screenshot):
            self.log("    日常结算后二次进入索拉指南，已显示素材获取页；正常结算完成，跳过幻梦游园。")
        else:
            self.log("    索拉指南未自动进入周度游历页，判定本周周常已经完成；本次跳过幻梦游园。")
        self._tap_ratio(0.957, 0.058, 0.35)

    def _perform_4c_main_attack(self) -> None:
        """Keep a steady main-character attack rhythm matching the healer clicks."""
        self.controller.left_click()
        self._sleep_interruptible(self.MAIN_ATTACK_CLICK_INTERVAL)

    def _cast_timed_ultimate(
        self,
        ultimate_key: str,
        attack_enabled: threading.Event,
        attack_lock: threading.Lock,
        *, resume_attacks: bool = True, settle_delay: float = 0.8,
    ) -> None:
        """Give the ultimate input a quiet window without competing attack clicks."""
        attack_enabled.clear()
        with attack_lock:
            pass
        try:
            if self.stop_event.is_set():
                return
            self._combat_animation_until = time.monotonic()+5.
            self.controller.press_binding(ultimate_key, 120)
            self._sleep_interruptible(settle_delay)
        finally:
            if resume_attacks and not self.stop_event.is_set():
                attack_enabled.set()

    def _confirm_daily_battle_finished(self, screenshot: Path) -> bool:
        """Confirm an initial missing task marker before sending more combat input."""
        for _ in range(1, self.DAILY_TASK_MISSING_CONFIRMATIONS):
            self._sleep_interruptible(self.DAILY_TASK_MISSING_CONFIRMATION_INTERVAL)
            if self.stop_event.is_set():
                return True
            self._capture_for_matching(screenshot)
            if time.monotonic() < self._combat_animation_until:
                return False
            if self._daily_battle_task_present(screenshot):
                return False
        return True

    def _perform_4c_heal_rotation(self, skill_key: str) -> bool:
        """Third-slot heal combo with short attack spacing and a clear return delay."""
        if self.stop_event.is_set():
            return False
        self.controller.press_key("3", 65)
        self._sleep_interruptible(self.HEAL_SWITCH_SETTLE_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_binding(skill_key, 65)
        self._sleep_interruptible(0.08)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("SPACE", 50)
        self._sleep_interruptible(0.035)
        for click_index in range(3):
            if self.stop_event.is_set():
                return False
            self.controller.left_click()
            if click_index < 2:
                self._sleep_interruptible(self.HEAL_ATTACK_CLICK_INTERVAL)
        self._sleep_interruptible(self.HEAL_RETURN_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("SPACE", 50)
        self._sleep_interruptible(0.035)
        for click_index in range(3):
            if self.stop_event.is_set():
                return False
            self.controller.left_click()
            if click_index < 2:
                self._sleep_interruptible(self.HEAL_ATTACK_CLICK_INTERVAL)
        if self.stop_event.is_set():
            return False
        self._sleep_interruptible(self.HEAL_ATTACK_TO_Q_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("Q", 120)
        self._sleep_interruptible(self.HEAL_Q_TO_RETURN_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("1", 65)
        self._sleep_interruptible(0.22)
        return not self.stop_event.is_set()

    def _collect_4c_reward(self, cycle_index: int) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + self.REWARD_SEARCH_TIMEOUT
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            self._capture_for_matching(screenshot)
            with Image.open(screenshot) as captured:
                scale = captured.width / 1920.0
            prompt, prompt_name = self._find_4c_absorb_prompt(screenshot, scale)
            if prompt is not None:
                self.log(
                    f"    第{cycle_index}轮：发现吸收提示 {prompt_name}，"
                    f"相似度 {prompt.score:.3f}，立即按 F。"
                )
                self.controller.release_keys()
                self.controller.press_key("F", 100)
                self._sleep_interruptible(2.8)
                return
            if self.stop_event.is_set():
                return
            self.controller.press_keys(("W",), 400)
            self.log(f"    第{cycle_index}轮：未出现吸收提示，向前移动一小段后重新检查。")
            self._sleep_interruptible(0.10)
        raise RuntimeError("击败首领后向前搜索仍未找到“F / 吸收”提示，已停止循环。")

    def _approach_4c_gold_target(self, offset_x: float, screen_width: int) -> str:
        """Approach a visible echo without violating the right-only camera search."""
        centre_tolerance = screen_width * 0.045
        if offset_x < -centre_tolerance:
            # Keep the camera direction stable and strafe toward a visible target;
            # a full rightward wrap used to throw left-side echoes out of view.
            self.controller.press_keys(("W", "A"), 400)
            return "目标在左侧，向左前方靠近"
        if offset_x > centre_tolerance:
            turn = int(max(110, min(360, offset_x * 0.40)))
            self.controller.move_mouse_relative(turn, 0)
            self.controller.press_keys(("W",), 360)
            return "目标在右侧，向右微调并靠近"
        self.controller.press_keys(("W",), 500)
        return "目标已在中央，直线靠近"

    def _find_4c_absorb_prompt(self, screenshot: Path, scale: float, *, fast: bool = False):
        best = None
        best_name = ""
        with Image.open(screenshot) as captured:
            width, height = captured.size
        prompt_region = (
            round(width * 0.42),
            round(height * 0.22),
            round(width * 0.96),
            round(height * 0.86),
        )
        scales = []
        candidates = ((scale, scale * 0.97, scale * 1.03) if fast else
                      (scale, scale * 0.94, scale * 0.97, scale * 1.03, scale * 1.06, scale * 0.88, scale * 1.12))
        for candidate in candidates:
            if candidate > 0.2 and all(abs(candidate - known) > 0.01 for known in scales):
                scales.append(candidate)
        for template_name in self.ABSORB_PROMPT_TEMPLATES:
            text_crop = self.ABSORB_TEXT_CROPS[template_name]
            for candidate_scale in scales:
                try:
                    match = self.matcher.find_fast(
                        screenshot,
                        template_name,
                        threshold=0.80,
                        scale=candidate_scale,
                        region=prompt_region,
                        template_crop=text_crop,
                    )
                except Exception:
                    continue
                if best is None or match.score > best.score:
                    best = match
                    best_name = template_name
                if fast or match.score >= 0.90:
                    return match, template_name
        return best, best_name

    def _restart_4c_challenge(self, next_cycle: int) -> None:
        self.log(f"    吸收完成，按 Esc 并准备第 {next_cycle} 轮。")
        self.controller.press_key("ESC", 70)
        self._sleep_interruptible(0.85)
        probe = Step(
            action="tap_image",
            template="restart_challenge.png",
            threshold=0.75,
            timeout=10.0,
            offset_x=0,
            offset_y=0,
        )
        x, y, score = self._find_image(probe)
        self.log(f"    找到重新挑战按钮：({x}, {y})，相似度 {score:.3f}。")
        self.controller.tap(x, y)
        self._sleep_interruptible(3.0)

    @staticmethod
    def _boss_health_ratio(screenshot: Path) -> float:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        expected_game_height = round(width * 9 / 16)
        titlebar_height = max(0, height - expected_game_height)
        game_height = height - titlebar_height
        top = max(0, titlebar_height + round(game_height * 0.035))
        bottom = min(height, titlebar_height + round(game_height * 0.070))
        left = max(0, round(width * 0.34))
        right = min(width, round(width * 0.66))
        region = image[top:bottom, left:right]
        if region.size == 0:
            return 0.0
        red = region[:, :, 0].astype(np.float32)
        green = region[:, :, 1].astype(np.float32)
        blue = region[:, :, 2].astype(np.float32)
        colored_health = (
            (red > 145)
            & (red > green * 1.12)
            & (red > blue * 1.22)
            & ((green > 55) | (red > 190))
        )
        return float(colored_health.mean())

    @staticmethod
    def _boss_name_ratio(screenshot: Path) -> float:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB")).astype(np.float32)
        height, width = image.shape[:2]
        titlebar_height = max(0, height - round(width * 9 / 16))
        game_height = height - titlebar_height
        top = titlebar_height + round(game_height * 0.008)
        bottom = titlebar_height + round(game_height * 0.045)
        left, right = round(width * 0.34), round(width * 0.66)
        region = image[top:bottom, left:right]
        if region.size == 0:
            return 0.0
        high = region.max(axis=2)
        low = region.min(axis=2)
        bright_name = (
            (region[:, :, 0] > 165)
            & (region[:, :, 1] > 155)
            & (region[:, :, 2] > 145)
            & ((high - low) < 95)
        )
        return float(bright_name.mean())

    @staticmethod
    def _boss_bar_track_score(screenshot: Path) -> float:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB")).astype(np.float32)
        height, width = image.shape[:2]
        titlebar_height = max(0, height - round(width * 9 / 16))
        game_height = height - titlebar_height
        top = titlebar_height + round(game_height * 0.035)
        bottom = titlebar_height + round(game_height * 0.075)
        left, right = round(width * 0.34), round(width * 0.66)
        region = image[top:bottom, left:right]
        if region.size == 0:
            return 0.0
        high = region.max(axis=2)
        low = region.min(axis=2)
        neutral_track = ((high - low) < 45) & (high > 85)
        return float(neutral_track.mean(axis=1).max())

    @staticmethod
    def _gold_target_location(screenshot: Path) -> tuple[float, int | None, int | None]:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        # High signs are excluded. The lower world view remains searchable because
        # a small echo can sit near the character; lower candidates must be more
        # solid so hollow golden combat rings are rejected.
        top, bottom = round(height * 0.18), round(height * 0.84)
        left, right = round(width * 0.08), round(width * 0.92)
        region = image[top:bottom, left:right]
        red = region[:, :, 0].astype(np.float32)
        green = region[:, :, 1].astype(np.float32)
        blue = region[:, :, 2].astype(np.float32)
        # Absorbable echoes are a saturated deep orange-gold. Pale yellow-white
        # reflections and floor lights must not be treated as navigation targets.
        maximum = np.maximum.reduce((red, green, blue))
        minimum = np.minimum.reduce((red, green, blue))
        saturation = (maximum - minimum) / np.maximum(maximum, 1.0)
        gold = (
            (red > 150)
            & (green > 85)
            & (blue < 145)
            & (saturation >= 0.42)
            & ((red - green) > 18)
            & ((green - blue) > 18)
        )
        if not gold.any():
            return 0.0, None, None

        # Downsample once and lightly join glow fragments. The component filter
        # below accepts small compact echoes, but rejects long rails and streaks.
        sample_step = 3
        sampled = gold[::sample_step, ::sample_step]
        padded = np.pad(sampled, 1, mode="constant")
        expanded = np.logical_or.reduce(
            [
                padded[dy : dy + sampled.shape[0], dx : dx + sampled.shape[1]]
                for dy in range(3)
                for dx in range(3)
            ]
        )

        visited = np.zeros(expanded.shape, dtype=bool)
        best_points: list[tuple[int, int]] = []
        best_score = 0.0
        best_confidence = 0.0
        rows, columns = expanded.shape
        for start_y, start_x in zip(*np.nonzero(expanded & ~visited)):
            if visited[start_y, start_x]:
                continue
            stack = [(int(start_y), int(start_x))]
            visited[start_y, start_x] = True
            points = []
            while stack:
                y, x = stack.pop()
                points.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < rows and 0 <= nx < columns and expanded[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
            ys = [point[0] for point in points]
            xs = [point[1] for point in points]
            component_height = max(ys) - min(ys) + 1
            component_width = max(xs) - min(xs) + 1
            aspect = max(component_width / component_height, component_height / component_width)
            compactness = len(points) / max(1, component_width * component_height)
            component_center_y = (sum(ys) / len(ys)) * sample_step + top
            component_center_x = (sum(xs) / len(xs)) * sample_step
            minimum_compactness = 0.68 if component_center_y > height * 0.60 else 0.43
            valid_shape = aspect <= 2.05 or (
                component_width > component_height and aspect <= 2.80
            )
            # A common false positive is the small gold ring mounted beneath the
            # large yellow MILITECH billboard. Reject a candidate when a broad,
            # dense gold panel occupies the area well above it. Real echoes do not
            # have a billboard-sized gold slab suspended over their position.
            overhead = gold[
                max(0, round(component_center_y - top - height * 0.40)):
                max(1, round(component_center_y - top - height * 0.10)),
                max(0, round(component_center_x - width * 0.16)):
                min(gold.shape[1], round(component_center_x + width * 0.16)),
            ]
            overhead_gold_ratio = float(overhead.mean()) if overhead.size else 0.0
            # Distant echoes form a medium-sized compact cluster. Tiny golden UI
            # marks and large billboards sit outside this range; a very close echo
            # is handled by the F/absorb prompt before colour navigation runs.
            if (
                len(points) < 100
                or len(points) > 1400
                or not valid_shape
                or compactness < minimum_compactness
                or overhead_gold_ratio > 0.055
            ):
                continue
            score = len(points) * compactness
            if score > best_score:
                best_score = score
                best_points = points
                best_confidence = compactness

        if not best_points:
            return float(len(best_points) / max(1, expanded.size)), None, None
        ys = np.fromiter((point[0] for point in best_points), dtype=np.float32)
        xs = np.fromiter((point[1] for point in best_points), dtype=np.float32)
        return (
            float(best_confidence),
            round(float(xs.mean()) * sample_step + left),
            round(float(ys.mean()) * sample_step + top),
        )

    def _run_visual_navigation(self, step: Step) -> None:
        if not hasattr(self.controller, "press_keys"):
            raise RuntimeError("群声共振模拟域目前只支持 PC 客户端窗口。")
        if not step.template:
            raise ValueError("视觉导航步骤需要填写交互提示模板。")
        target_templates = step.templates or ["npc_far.png", "npc_near.png"]
        deadline = time.monotonic() + max(5.0, step.timeout)
        misses = 0
        screenshot = APP_DIR / "_runtime_screenshot.png"
        try:
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    self.log("    收到停止信号，已停止移动并释放方向键。")
                    return
                self._capture_for_matching(screenshot)
                scale = float(getattr(self.controller, "scale", 1.0))

                try:
                    prompt = self.matcher.find_fast(
                        screenshot,
                        step.template,
                        threshold=max(0.70, step.threshold),
                        scale=scale,
                    )
                except Exception:
                    prompt = None
                if prompt is not None:
                    self.log(f"    已靠近守岸人，交互提示相似度 {prompt.score:.3f}。")
                    if self.dry_run:
                        self.log("    干运行：已识别 F 交互提示，但不按键。")
                    else:
                        self.controller.release_keys()
                        self.controller.press_key("F", 90)
                        self.log("    已松开方向键并按下 F。")
                    return

                best = None
                best_name = ""
                for template_name in target_templates:
                    try:
                        candidate = self.matcher.find(screenshot, template_name, -1.0, [scale])
                    except Exception:
                        continue
                    if best is None or candidate.score > best.score:
                        best = candidate
                        best_name = template_name

                if best is None or best.score < step.threshold:
                    misses += 1
                    self.log(f"    暂未定位到蓝色守岸人（{misses}/4），保持原地重新观察。")
                    if misses >= 4:
                        raise RuntimeError("连续 4 次没有定位到蓝色守岸人，已停止移动。请让角色与守岸人同时出现在画面中。")
                    self._sleep_interruptible(0.18)
                    continue

                misses = 0
                with Image.open(screenshot) as captured:
                    width, height = captured.size
                target_x, target_y = best.center
                anchor_x, anchor_y = width * 0.52, height * 0.51
                dx, dy = target_x - anchor_x, target_y - anchor_y
                dead_x, dead_y = width * 0.025, height * 0.03
                keys: list[str] = []
                if dy < -dead_y:
                    keys.append("W")
                elif dy > dead_y:
                    keys.append("S")
                if dx < -dead_x:
                    keys.append("A")
                elif dx > dead_x:
                    keys.append("D")
                if not keys:
                    keys.append("W")

                distance = (dx * dx + dy * dy) ** 0.5
                pulse_ms = min(max(step.duration_ms, 60), 180)
                if distance < max(width, height) * 0.10:
                    pulse_ms = min(pulse_ms, 80)
                elif distance < max(width, height) * 0.20:
                    pulse_ms = min(pulse_ms, 120)
                self.log(
                    f"    {best_name} 相似度 {best.score:.3f}，目标偏移 "
                    f"({dx:+.0f}, {dy:+.0f})，短按 {'+'.join(keys)} {pulse_ms}ms。"
                )
                if self.dry_run:
                    self.log("    干运行：已算出移动方向，但不发送键盘操作。")
                    return
                self.controller.press_keys(keys, pulse_ms)
                self._sleep_interruptible(0.12)
            raise RuntimeError("靠近守岸人超时，已停止移动并释放方向键。")
        finally:
            if not self.dry_run:
                try:
                    self.controller.release_keys()
                except Exception as exc:
                    self.log(f"    释放方向键时遇到问题: {exc}")

    def _run_image_cycle(self, step: Step) -> None:
        templates = step.templates or self._numbered_templates("menu", 2, 99)
        if not templates:
            raise RuntimeError("循环模板列表为空。")
        steps = []
        for template_name in templates:
            if not (self.template_root / template_name).exists():
                if not step.skip_missing:
                    raise FileNotFoundError(f"模板不存在: {template_name}")
                continue
            steps.append(Step(
                action="tap_image", label=f"识别并点击 {template_name}", template=template_name,
                threshold=step.threshold, timeout=step.timeout,
                offset_x=self._template_offset(step, template_name, "x"),
                offset_y=self._template_offset(step, template_name, "y"), seconds=step.seconds))
        if not steps:
            raise RuntimeError("没有可用的循环模板，请检查模板组。")
        previous_step = self.last_clicked_image_step
        round_index = 1
        while not self.stop_event.is_set():
            if self.max_cycles is not None and round_index > self.max_cycles:
                self.log(f"    已完成 {self.max_cycles} 轮循环，自动停止。")
                self.stop_event.set()
                return
            self.log(f"    开始第 {round_index} 轮循环。")
            cursor = 0
            while cursor < len(steps):
                if self.stop_event.is_set():
                    self.log("收到停止信号，循环任务已中断。")
                    return
                current = steps[cursor]
                next_step = steps[cursor + 1] if cursor + 1 < len(steps) else None
                wraps = next_step is None and step.loop and (self.max_cycles is None or round_index < self.max_cycles)
                if wraps and len(steps) > 1:
                    next_step = steps[0]
                matched, x, y, score = self._wait_for_cycle_template(current, previous_step, next_step)
                if self.stop_event.is_set():
                    return
                self.log(f"    找到 {matched.template}: ({x}, {y}) 相似度 {score:.3f}")
                if self.dry_run:
                    self.log("    干运行：已识别位置，但不点击。")
                else:
                    self._click_cycle_template(matched, x, y)
                previous_step = matched
                self._sleep_click_interval(step.seconds)
                if matched is next_step:
                    if wraps:
                        round_index += 1
                        self.log(f"    已进入第 {round_index} 轮，从已匹配的首张模板接续。")
                        cursor = 1
                        continue
                    cursor += 2
                else:
                    cursor += 1
            if not step.loop:
                return
            if self.max_cycles is not None and round_index >= self.max_cycles:
                if previous_step is not None and not self.dry_run:
                    self._verify_final_cycle_click(previous_step)
                self.log(f"    已完成 {self.max_cycles} 轮循环，自动停止。")
                self.stop_event.set()
                return
            round_index += 1

    def _wait_for_cycle_template(
        self,
        step: Step,
        previous_step: Step | None = None,
        next_step: Step | None = None,
    ) -> tuple[Step, int, int, float]:
        found = self._probe_cycle_template(step, "本次")
        if found is not None:
            return step, *found
        if previous_step is not None:
            found = self._probe_cycle_template(previous_step, "上一张", attempts=CYCLE_NEIGHBOR_PROBE_ATTEMPTS)
            if found is not None:
                if self.dry_run:
                    self.log("    干运行：上一张匹配成功，不点击。")
                else:
                    self.log(f"    上一张 {previous_step.template} 重新匹配成功，按新识别坐标点击后回到本次步骤。")
                    self._click_cycle_template(previous_step, *found[:2], recovery=True)
                    self._sleep_click_interval(previous_step.seconds)
                found = self._probe_cycle_template(step, "本次（上一张匹配后）")
                if found is not None:
                    return step, *found
        if next_step is not None:
            found = self._probe_cycle_template(next_step, "下一张", attempts=CYCLE_NEIGHBOR_PROBE_ATTEMPTS)
            if found is not None:
                self.log(f"    已显示下一张 {next_step.template}，跳过本次 {step.template}，从下一张接续。")
                return next_step, *found
        found = self._probe_cycle_template(step, "本次（最终复核）")
        if found is not None:
            return step, *found
        previous_name = previous_step.template if previous_step else "无上一张"
        next_name = next_step.template if next_step else "无下一张"
        message = (f"周常模板流程无法继续：本次 {step.template}、上一张 {previous_name}、"
                   f"下一张 {next_name} 已按当前模板{CYCLE_PROBE_ATTEMPTS}次、附近模板各{CYCLE_NEIGHBOR_PROBE_ATTEMPTS}次"
                   f"识别并最终复核本次，仍未匹配。已停止，请检查当前游戏页面。")
        self.stop_event.set()
        self.log(message)
        self.notice(message)
        raise RuntimeError(message)

    def _probe_cycle_template(self, step: Step, stage: str, *, attempts: int = CYCLE_PROBE_ATTEMPTS) -> tuple[int, int, float] | None:
        for attempt in range(attempts):
            if self.stop_event.is_set():
                raise RuntimeError("循环任务已停止。")
            try:
                found = self._find_image(step, single_attempt=True)
                if self.stop_event.is_set():
                    raise RuntimeError("循环任务已停止。")
                return found
            except WeeklyLimitReached:
                raise
            except (FileNotFoundError, OSError):
                raise
            except Exception as exc:
                if self.stop_event.is_set():
                    raise RuntimeError("循环任务已停止。") from exc
                self.log(f"    {stage}识别 {step.template}（{attempt+1}/{attempts}）未匹配: {exc}")
                if attempt + 1 < attempts:
                    self._sleep_interruptible(CYCLE_PROBE_INTERVAL)
        return None

    def _click_cycle_template(self, step: Step, x: int, y: int, recovery: bool = False):
        if self.stop_event.is_set():
            return
        action = "重新识别匹配后点击" if recovery else "正在点击识别坐标"
        self.log(f"    {action}: ({x}, {y})")
        result = self.controller.tap(x, y)
        if isinstance(result, dict):
            self.log(
                "    鼠标移动结果: "
                f"目标{result.get('target')}，"
                f"移动后{result.get('after_move')}，"
                f"SetCursorPos={result.get('set_cursor_ok')}"
            )
            if not result.get("set_cursor_ok"):
                self.log("    鼠标没有移动成功：请尝试右键桌面快捷方式，以管理员身份运行。")
        self.last_clicked_image_step = step
        if (self._weekly_monitoring and self._weekly_observed_target is not None
                and self._weekly_observed_target.template == step.template):
            self._weekly_pending_click = self._weekly_observed_target
            self._weekly_click_at = time.monotonic()
        return result

    def _wait_weekly_click_response(self) -> bool:
        pending = self._weekly_pending_click
        if pending is None:
            return True
        remaining = self._weekly_click_at + WEEKLY_CLICK_INTERVAL - time.monotonic()
        if remaining > 0:
            self._sleep_interruptible(remaining)
        deadline = self._weekly_click_at + WEEKLY_RESPONSE_TIMEOUT
        screenshot = APP_DIR / '_runtime_screenshot.png'
        while not self.stop_event.is_set():
            self._capture_for_matching(screenshot)
            self._check_weekly_cap(screenshot)
            if self.stop_event.is_set():
                raise RuntimeError('周常已停止。')
            if pending.click_responded(screenshot, self.matcher):
                self._weekly_pending_click = None
                self.log(f"    已确认 {pending.template} 点击后画面有响应，再识别下一步。")
                return True
            if time.monotonic() >= deadline:
                self.log(f"    {pending.template} 点击后画面未确认变化，暂停推进，仅允许重新识别上一按钮。")
                return False
            self._sleep_interruptible(CYCLE_PROBE_INTERVAL)
        raise RuntimeError('周常已停止。')

    def _verify_final_cycle_click(self, final_step: Step) -> None:
        probe = replace(final_step, timeout=min(max(final_step.timeout, 0.5), 1.0))
        self.log(f"    最终轮验证：确认 {final_step.template} 已响应点击。")
        for retry_index in range(CYCLE_FINAL_MAX_RETRIES + 1):
            if self._weekly_monitoring:
                if self._weekly_pending_click is not None and self._wait_weekly_click_response():
                    self.log(f"    最终轮验证通过：{final_step.template} 点击后画面已响应。")
                    return
            try:
                x, y, score = self._find_image(probe)
            except WeeklyLimitReached:
                raise
            except Exception:
                if self._weekly_monitoring and self._weekly_pending_click is not None:
                    if self._wait_weekly_click_response():
                        self.log('    最终轮验证通过：点击响应已确认。')
                        return
                    self.stop_event.set()
                    raise RuntimeError(f'最终点击 {final_step.template} 未确认响应，已停止，不将遮罩或过渡帧当作完成。')
                self.log(f"    最终轮验证通过：{final_step.template} 已离开当前画面。")
                return

            if retry_index >= CYCLE_FINAL_MAX_RETRIES:
                self.stop_event.set()
                raise RuntimeError(
                    f"最终模板 {final_step.template} 重新匹配并点击 {CYCLE_FINAL_MAX_RETRIES} 次后仍停留在画面，"
                    "任务已自动停止，请检查游戏状态。"
                )

            self.log(
                f"    最终轮回退命中 {final_step.template}: ({x}, {y}) "
                f"相似度 {score:.3f}，匹配成功后执行第 {retry_index + 1}/{CYCLE_FINAL_MAX_RETRIES} 次点击。"
            )
            self._click_cycle_template(final_step, x, y, recovery=True)
            self._sleep_click_interval(final_step.seconds)

    def _sleep_interruptible(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.stop_event.is_set():
                return
            time.sleep(min(0.1, deadline - time.time()))

    def _sleep_click_interval(self, base_seconds: float) -> None:
        jitter = CLICK_DELAY_JITTER_SECONDS
        if self._weekly_monitoring:
            base_seconds = WEEKLY_CLICK_INTERVAL
            jitter = WEEKLY_CLICK_JITTER
        minimum = max(0.0, base_seconds - jitter)
        maximum = max(minimum, base_seconds + jitter)
        self._sleep_interruptible(random.uniform(minimum, maximum))

    def _numbered_templates(self, prefix: str, start: int, end: int) -> list[str]:
        names = []
        for path in self.template_root.glob(f"{prefix}*.png"):
            match = re.fullmatch(rf"{re.escape(prefix)}(\d+)\.png", path.name)
            if not match:
                continue
            number = int(match.group(1))
            if start <= number <= end:
                names.append((number, path.name))
        return [name for _number, name in sorted(names)]

    @staticmethod
    def _template_offset(step: Step, template_name: str, axis: str) -> int:
        specific = step.template_offsets.get(template_name, {})
        value = specific.get(axis)
        if value is not None:
            return int(value)
        return step.offset_x if axis == "x" else step.offset_y

    def _find_image(self, step: Step, *, single_attempt: bool = False) -> tuple[int, int, float]:
        if not step.template:
            raise ValueError("tap_image 步骤需要 template 字段")
        deadline = time.time() + step.timeout
        last_error: Exception | None = None
        weekly = self._weekly_monitoring
        if (weekly and not self.dry_run and self._weekly_pending_click is not None
                and step.template != self._weekly_pending_click.template
                and not self._wait_weekly_click_response()):
            raise RuntimeError('上一点击未确认响应，不点击下一步；进入限次重新识别。')
        previous_target = None
        frames = 0
        while single_attempt or time.time() <= deadline:
            if self.stop_event.is_set():
                raise RuntimeError("已停止模板识别。")
            screenshot = APP_DIR / "_runtime_screenshot.png"
            self._capture_for_matching(screenshot)
            frames += 1
            if self._weekly_monitoring and not self.dry_run:
                self._check_weekly_cap(screenshot)
            try:
                scales = self._fast_scales()
                if self._weekly_monitoring:
                    from weekly_clicks import WeeklyTarget, weekly_template_crop, weekly_target_clickable
                    crop = weekly_template_crop(step.template, self.matcher.templates_dir)
                    options = {'template_crop': crop} if crop is not None else {}
                    def clickable(candidate):
                        observed = WeeklyTarget.read(screenshot, step.template, candidate, self.matcher.templates_dir, crop)
                        return weekly_target_clickable(observed, candidate.score)
                    match = self.matcher.find(screenshot, step.template, WEEKLY_TEMPLATE_THRESHOLD,
                                              scales, first_match=True, max_width=1280,
                                              candidate_validator=clickable, **options)
                    target = WeeklyTarget.read(screenshot, step.template, match, self.matcher.templates_dir, crop)
                    if not weekly_target_clickable(target, match.score):
                        raise RuntimeError(f'{step.template} 颜色或按钮文字不符，等待可点击按钮。')
                    stable = previous_target is not None and previous_target.stable_with(target)
                    if not stable:
                        previous_target = target
                        if single_attempt and frames >= 2:
                            raise RuntimeError(f'{step.template} 连续截图位置或画面未稳定，暂不点击。')
                        self._sleep_interruptible(WEEKLY_STABLE_INTERVAL)
                        continue
                    self._weekly_observed_target = target
                else:
                    match = self.matcher.find(screenshot, step.template, step.threshold, scales)
                offset_x = 0 if weekly and crop is not None and step.template == 'menu1.png' and step.offset_x == 80 else step.offset_x
                image_x, image_y = self._random_click_point(match, offset_x, step.offset_y,
                    jitter_ratio=.05) if weekly else self._random_click_point(match, step.offset_x, step.offset_y)
                if self.debug_matches:
                    self._save_match_debug(screenshot, step.template, match, image_x, image_y)
                if hasattr(self.controller, "screenshot_to_screen"):
                    screen_x, screen_y = self.controller.screenshot_to_screen(image_x, image_y)
                    self.log(f"    截图坐标 ({image_x}, {image_y}) 将点击屏幕坐标 ({screen_x}, {screen_y})")
                    return image_x, image_y, match.score
                if hasattr(self.controller, "screenshot_to_client"):
                    client_x, client_y = self.controller.screenshot_to_client(image_x, image_y)
                    self.log(f"    截图坐标 ({image_x}, {image_y}) 已换算为窗口坐标 ({client_x}, {client_y})")
                    return client_x, client_y, match.score
                return image_x, image_y, match.score
            except Exception as exc:
                if single_attempt:
                    raise
                last_error = exc
                previous_target = None
                self._sleep_interruptible(.15 if weekly else .6)
        raise RuntimeError(str(last_error) if last_error else f"识别超时: {step.template}")

    def _check_weekly_cap(self, screenshot: Path) -> None:
        vision = WeeklyRewardsVision(TEMPLATES_DIR / "weekly")
        page = vision.cap_page(screenshot)
        if page is None:
            return
        if self.stop_event.is_set():
            raise RuntimeError("周常收尾已停止。")
        self.log("识别到本周游历值已达到上限，不再点击重新挑战。")

        def wait_for(predicate, label):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    raise RuntimeError("周常收尾已停止。")
                self._capture_for_matching(screenshot)
                if predicate(screenshot):
                    return
                self._sleep_interruptible(0.25)
            raise RuntimeError(f"周常收尾等待{label}超时，已停止点击。")

        if page == "result":
            self._tap_ratio(0.664, 0.848, 0.4)
            wait_for(lambda path: vision.cap_page(path) == "home", "幻梦游园主页")
        if self.stop_event.is_set():
            raise RuntimeError("周常收尾已停止。")
        self._tap_ratio(0.940, 0.0565, 0.4)
        wait_for(vision.weekly_page, "周度游历页面")
        claimed_any = False
        for _ in range(6):
            if self.stop_event.is_set():
                raise RuntimeError("周常领奖已停止。")
            if vision.all_claimed(screenshot):
                self.log("所有周常宝箱均已领取，跳过点击。")
                raise WeeklyLimitReached()
            target = vision.rightmost_claimable(screenshot)
            if target is None:
                if claimed_any:
                    self.log("已确认宝箱变为已领取状态，当前没有其他发光宝箱。")
                    raise WeeklyLimitReached()
                break
            self.log(f"领取当前最右侧可领取宝箱：{target}。")
            self.controller.tap(*target)
            self._sleep_interruptible(0.6)
            self._dismiss_reward_overlay_safely()
            wait_for(vision.weekly_page, "领奖后的周度游历页面")
            wait_for(lambda path: vision.claimed_at(path, target), "宝箱领取状态确认")
            claimed_any = True
        if claimed_any and vision.rightmost_claimable(screenshot) is None:
            raise WeeklyLimitReached()
        self.weekly_rewards_pending = True
        self.log("本周游历已达上限；暂无法确认可领取宝箱，请手动检查，本次不会自动关机。")
        self.notice("周常已达到上限，已回到周度游历。无法确认宝箱领取状态，请检查是否需要手动领取；本次不会自动关机。")
        raise WeeklyLimitReached()

    @staticmethod
    def _random_click_point(match, offset_x: int, offset_y: int, *, jitter_ratio=CLICK_JITTER_RATIO) -> tuple[int, int]:
        margin_x = min(max(1, int(round(match.width * CLICK_EDGE_MARGIN_RATIO))), max(1, (match.width - 1) // 2))
        margin_y = min(max(1, int(round(match.height * CLICK_EDGE_MARGIN_RATIO))), max(1, (match.height - 1) // 2))
        safe_left = match.x + margin_x
        safe_right = match.x + match.width - 1 - margin_x
        safe_top = match.y + margin_y
        safe_bottom = match.y + match.height - 1 - margin_y

        anchor_x = min(max(match.center[0] + offset_x, safe_left), safe_right)
        anchor_y = min(max(match.center[1] + offset_y, safe_top), safe_bottom)
        jitter_x = max(1, int(round(match.width * jitter_ratio)))
        jitter_y = max(1, int(round(match.height * jitter_ratio)))

        left = max(safe_left, anchor_x - jitter_x)
        right = min(safe_right, anchor_x + jitter_x)
        top = max(safe_top, anchor_y - jitter_y)
        bottom = min(safe_bottom, anchor_y + jitter_y)
        return random.randint(left, right), random.randint(top, bottom)

    def _fast_scales(self) -> list[float]:
        if hasattr(self.controller, "template_scales"):
            scales = self.controller.template_scales()
            if isinstance(scales, (list, tuple)) and scales:
                return [float(scale) for scale in scales]
        return [1.0]

    def _save_match_debug(self, screenshot: Path, template_name: str, match, click_x: int, click_y: int) -> None:
        try:
            debug_dir = APP_DIR / "debug"
            debug_dir.mkdir(exist_ok=True)
            image = Image.open(screenshot).convert("RGB")
            draw = ImageDraw.Draw(image)
            draw.rectangle(
                [match.x, match.y, match.x + match.width, match.y + match.height],
                outline="red",
                width=4,
            )
            size = 28
            draw.line([click_x - size, click_y, click_x + size, click_y], fill="yellow", width=4)
            draw.line([click_x, click_y - size, click_x, click_y + size], fill="yellow", width=4)
            safe_name = template_name.replace("/", "_").replace("\\", "_")
            target = debug_dir / f"last_match_{safe_name}"
            image.save(target)
            self.log(f"    调试图已保存: {target}")
        except Exception as exc:
            self.log(f"    调试图保存失败: {exc}")

    def _capture_for_matching(self, target: Path) -> None:
        try:
            self.controller.screencap(target, bring_to_front=not self.dry_run)
        except TypeError:
            self.controller.screencap(target)

    @staticmethod
    def _require_xy(step: Step) -> None:
        if step.x is None or step.y is None:
            raise ValueError("tap 步骤需要 x/y")
