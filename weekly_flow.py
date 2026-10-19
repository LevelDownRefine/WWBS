"""Observe the weekly page on every action; repeated captions are action families."""
from dataclasses import dataclass
from pathlib import Path
import time

import numpy as np
from PIL import Image

from weekly_clicks import WeeklyTarget, weekly_target_clickable, weekly_template_crop


FAMILIES = {
    'start': ('menu1.png',),
    'confirm': ('menu2.png', 'menu94.png', 'menu98.png'),
    'next_day': ('menu3.png', 'menu5.png', 'menu7.png', 'menu9.png', 'menu92.png'),
    'skip': ('menu4.png', 'menu6.png', 'menu8.png', 'menu91.png'),
    'next_stage': ('menu93.png',), 'close': ('menu95.png',),
    'reward': ('menu96.png',), 'advance': ('menu97.png',), 'retry': ('menu99.png',),
}
LABELS = {'start': '开始游戏', 'confirm': '确认', 'next_day': '进入下一天', 'skip': '选卡／跳过',
          'next_stage': '进入新阶段', 'close': '关闭', 'reward': '阶段奖励',
          'advance': '继续', 'retry': '重新挑战'}


def family(template):
    name = Path(template).name
    return next((key for key, names in FAMILIES.items() if name in names), name)


@dataclass
class CardDecision:
    pixels: np.ndarray
    paper: np.ndarray

    @classmethod
    def read(cls, screenshot, target):
        """Only the three card interiors can acknowledge another identical skip page."""
        x = (target.box[0]+target.box[2])/2
        y = (target.box[1]+target.box[3])/2
        scale = target.scale
        patches = []
        with Image.open(screenshot) as source:
            for left, right in ((-790, -450), (-340, 20), (110, 470)):
                box = (round(x+left*scale), round(y-690*scale),
                       round(x+right*scale), round(y-120*scale))
                if box[0] < 0 or box[1] < 0 or box[2] > source.width or box[3] > source.height:
                    return None
                patches.append(np.asarray(source.crop(box).convert('RGB').resize((48, 72)), dtype=np.int16))
        pixels = np.stack(patches)
        paper = (pixels.mean(axis=3) > 135) & (np.ptp(pixels, axis=3) < 80)
        if any(float(mask.mean()) < .48 for mask in paper):
            return None
        return cls(pixels, paper)

    def stable_with(self, other):
        return other is not None and float(np.abs(self.pixels-other.pixels).mean()) < 4

    def changed_from(self, previous):
        return (previous is not None and float((np.abs(self.pixels-previous.pixels).mean(axis=3)[previous.paper] > 20).mean()) > .025)


@dataclass
class Page:
    template: str
    kind: str
    match: object
    target: WeeklyTarget
    day: int | None = None
    cards: CardDecision | None = None

    def stable_with(self, other):
        return (other is not None and self.kind == other.kind and self.day == other.day
                and self.target.stable_with(other.target)
                and (self.cards is None or self.cards.stable_with(other.cards)))


class WeeklyFlowVision:
    def __init__(self, matcher, templates, scales):
        self.matcher = matcher
        self.templates = tuple(dict.fromkeys(templates))
        self.scales = scales
        self.last_template = None
        self._template_scales = {}
        self._day_anchor = None
        self._day_pixels = None
        self._day_probe_at = float('-inf')

    def remaining_days(self, screenshot):
        with Image.open(screenshot) as source:
            width, height = source.size
        # The label and five trailing amber dots are a separate stage signal.
        cached = self._day_anchor
        if cached is not None:
            with Image.open(screenshot) as source:
                pixels = np.asarray(source.crop((cached.x, cached.y, cached.x+cached.width, cached.y+cached.height))
                                    .convert('RGB').resize((52, 27)), dtype=np.int16)
            if float(np.abs(pixels-self._day_pixels).mean()) > 12:
                self._day_anchor = cached = None
        if cached is None and time.monotonic()-self._day_probe_at < .75:
            return None
        scales = [None] if cached is not None else list(dict.fromkeys([*self.scales, 1.]))
        if cached is None:
            self._day_probe_at = time.monotonic()
        for scale in scales:
            try:
                match = cached or self.matcher.find_fast(screenshot, 'weekly/remaining_label.png', .86, scale,
                    region=(0, 0, width, max(90, round(height*.3))), max_width=1280)
            except RuntimeError:
                continue
            actual_scale = match.width/52
            dots = []
            with Image.open(screenshot) as source:
                for index in range(5):
                    cx = match.x+(150+40.5*index)*actual_scale
                    cy = match.y+15*actual_scale
                    radius = max(2, 5*actual_scale)
                    if cx+radius > source.width or cy+radius > source.height:
                        return None
                    pixels = np.asarray(source.crop((round(cx-radius), round(cy-radius),
                                                     round(cx+radius), round(cy+radius))).convert('RGB'))
                    amber = (pixels[:, :, 0] > 190) & (pixels[:, :, 1] > 110) & (pixels[:, :, 2] < 150)
                    dots.append(float(amber.mean()) > .5)
            count = sum(dots)
            if 1 <= count <= 5 and dots == [False]*(5-count)+[True]*count:
                self._day_anchor = match
                with Image.open(screenshot) as source:
                    self._day_pixels = np.asarray(source.crop((match.x, match.y, match.x+match.width, match.y+match.height))
                                                  .convert('RGB').resize((52, 27)), dtype=np.int16)
                return count
        return None

    def detect(self, screenshot, preferred=None, *, recovery=True, wide=False):
        groups = {}
        for name in self.templates:
            if (self.matcher.templates_dir/name).exists():
                groups.setdefault(family(name), []).append(name)
        order = [preferred] if preferred in groups else []
        if recovery:
            order += [key for key in groups if key not in order]
        # One representative of every family before checking decorative variants.
        choices = []
        for key in order:
            names = groups[key]
            first = self.last_template if self.last_template in names else names[0]
            choices.append(first)
        choices += [name for key in order for name in groups[key] if name not in choices]
        for name in choices:
            known_scale = self._template_scales.get(name, self.scales[0])
            scales = list(dict.fromkeys([known_scale, *self.scales])) if wide else [known_scale]
            crop = weekly_template_crop(name, self.matcher.templates_dir)
            def valid(candidate):
                target = WeeklyTarget.read(screenshot, name, candidate, self.matcher.templates_dir, crop)
                return weekly_target_clickable(target, candidate.score)
            try:
                # Global page identity needs stronger evidence than a nearby
                # positional recovery: a weak shared button outline is insufficient.
                match = self.matcher.find(screenshot, name, .8, scales, first_match=True,
                                          template_crop=crop, max_width=960, candidate_validator=valid)
            except RuntimeError:
                continue
            target = WeeklyTarget.read(screenshot, name, match, self.matcher.templates_dir, crop)
            self._template_scales[name] = target.scale
            kind = family(name)
            self.last_template = name
            return Page(name, kind, match, target, self.remaining_days(screenshot),
                        CardDecision.read(screenshot, target) if kind == 'skip' else None)
        return None


def run_weekly_flow(runner, start, cycle, *, attempts=5, nearby_attempts=2):
    """Resume anywhere, confirm every action, and never count skip repetitions as days."""
    names = cycle.templates or runner._numbered_templates('menu', 2, 99)
    names = list(dict.fromkeys([start.template, *names]))
    vision = WeeklyFlowVision(runner.matcher, names, runner._fast_scales())
    screenshot = runner.template_root.parent/'_runtime_weekly_flow.png'
    # The runtime file belongs alongside other screenshots, including custom roots.
    previous = pending = None
    preferred = 'start'
    misses = retries = completed = 0
    clicked_at = 0.
    last_action_at = time.monotonic()
    checked_skill = False
    limit = runner.max_cycles if runner.max_cycles is not None else (None if cycle.loop else 1)
    runner.log('周常按当前画面接续：重复按钮按页面类型处理，每次点击后重新确认；当前5次、附近各2次。')
    while not runner.stop_event.is_set():
        if time.monotonic()-last_action_at > 20:
            raise RuntimeError('周常20秒内无法确认稳定可操作页面，已停止。')
        runner._capture_for_matching(screenshot)
        runner._check_weekly_cap(screenshot)
        if runner.stop_event.is_set():
            return
        page = vision.detect(screenshot, preferred, recovery=pending is not None or misses < nearby_attempts,
                             wide=misses in (1, attempts-1))
        stable = page is not None and page.stable_with(previous)
        if pending is not None:
            responded = pending.target.click_responded(screenshot, runner.matcher)
            repeated_cards = (stable and page.kind == pending.kind == 'skip' and page.cards is not None
                              and page.cards.changed_from(pending.cards))
            changed_page = stable and page.kind != pending.kind
            changed_day = (stable and page.day is not None and pending.day is not None and page.day != pending.day)
            if responded or repeated_cards or changed_page or changed_day:
                runner.log('    已确认点击生效，重新按当前页面定位。')
                pending = None
                retries = 0
                misses = 0
            elif time.monotonic()-clicked_at < 4:
                misses = min(misses+1, attempts-1) if page is None else 0
                previous = page
                runner._sleep_interruptible(.12)
                continue
            elif not stable or page.kind != pending.kind:
                raise RuntimeError('周常点击后未确认新页面，已停止，不猜测后续步骤。')
            elif retries >= 2:
                raise RuntimeError('周常同一按钮重新识别点击2次后仍无响应，已停止。')
            else:
                retries += 1
                pending = None  # Fresh stable observation below supplies retry coordinates.
        if page is None:
            misses += 1
            if misses >= attempts:
                raise RuntimeError(f'周常当前模板已识别{attempts}次，附近模板各{nearby_attempts}次，无法确认页面，已停止。')
            previous = None
            runner._sleep_interruptible(.12)
            continue
        misses = 0
        preferred = page.kind
        if not stable:
            previous = page
            runner._sleep_interruptible(.15)
            continue
        if page.kind == 'start' and not checked_skill:
            runner._ensure_weekly_skill_selected()
            checked_skill = True
            previous = None
            continue
        if page.kind == 'retry' and (pending is None):
            if retries == 0:
                completed += 1
                runner.log(f'    已完成第{completed}轮（包含接续的当前轮）。')
            if limit is not None and completed >= limit:
                runner.log('周常已完成指定轮数，保留结算页面。')
                return
        source = start if page.kind == 'start' else cycle
        offset_x = 0 if page.kind == 'start' and source.offset_x == 80 else runner._template_offset(source, page.template, 'x')
        x, y = runner._random_click_point(page.match, offset_x,
                                         runner._template_offset(source, page.template, 'y'), jitter_ratio=.05)
        step = type(start)(action='tap_image', template=page.template)
        runner._weekly_observed_target = page.target
        day = f'，剩余{page.day}天' if page.day is not None else ''
        runner.log(f'    当前页面：{LABELS.get(page.kind, page.kind)}{day}；识别{page.template}后点击。')
        runner._click_cycle_template(step, x, y, recovery=retries > 0)
        runner._weekly_pending_click = None  # This flow owns acknowledgement and repeated card evidence.
        pending = page
        clicked_at = time.monotonic()
        last_action_at = clicked_at
        previous = None
        runner._sleep_click_interval(.3)
