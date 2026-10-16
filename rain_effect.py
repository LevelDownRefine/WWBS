"""Animated rain on glass: transparent sprites, water trails and fine falling rain."""
from dataclasses import dataclass, field
from functools import lru_cache
import math
from pathlib import Path
import random
import json

import numpy as np
from PIL import Image, ImageDraw


RAIN_LEVELS = {'轻雨': (55, 26), '中雨': (115, 60), '大雨': (200, 105)}
RAIN_STRENGTHS = {'柔和': 155, '标准': 220, '明显': 255}
RAIN_MODES = ('关闭', '持续下雨', 'Boss战自动')
DEFAULT_RAIN = {'mode': '关闭', 'level': '中雨', 'strength': '标准', 'volume': 30}


def normalize_rain_settings(raw):
    raw = raw if isinstance(raw, dict) else {}
    volume = raw.get('volume', 30)
    if type(volume) is not int:
        volume = 30
    return {'mode': raw.get('mode') if raw.get('mode') in RAIN_MODES else '关闭',
            'level': raw.get('level') if raw.get('level') in RAIN_LEVELS else '中雨',
            'strength': raw.get('strength') if raw.get('strength') in RAIN_STRENGTHS else '标准',
            'volume': max(0, min(100, volume))}


def load_rain_settings(path: Path):
    try:
        return normalize_rain_settings(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return dict(DEFAULT_RAIN)


@lru_cache(maxsize=16)
def water_drop(radius: int):
    """Soft glass bead: shaded lower rim, bright upper rim and a tiny glint."""
    scale = 3
    width, height = radius*2+6, radius*3+6
    yy, xx = np.mgrid[:height*scale, :width*scale].astype(np.float32)/scale
    x = (xx-width/2)/(radius*.88)
    y = (yy-height/2)/(radius*1.22)
    distance = np.sqrt(x*x+y*y)
    body = np.maximum(0, 1-distance)
    rim = np.exp(-((distance-.88)/.09)**2)
    illumination = np.clip((-x-y)*.55, -.8, 1)
    highlight = np.maximum(illumination, 0)*rim
    shadow = np.maximum(-illumination, 0)*rim
    glint = np.exp(-((x+.32)**2+(y+.42)**2)/.018)
    lower_glint = np.exp(-((x-.32)**2+(y-.7)**2)/.035)
    alpha = (body*16+highlight*160+shadow*100+glint*205+lower_glint*65)
    alpha *= np.clip((1.04-distance)*14, 0, 1)
    pixels = np.zeros((height*scale, width*scale, 4), dtype=np.uint8)
    bright = np.clip(highlight+glint*2+lower_glint, 0, 1)
    for index, (low, high) in enumerate(((26, 230), (48, 246), (66, 255))):
        pixels[:, :, index] = (low+(high-low)*bright).astype(np.uint8)
    pixels[:, :, 3] = np.clip(alpha, 0, 235).astype(np.uint8)
    return Image.fromarray(pixels).resize((width, height), Image.Resampling.LANCZOS)


@dataclass
class GlassDrop:
    x: float
    y: float
    radius: int
    wait: float
    speed: float
    phase: float
    trail: list = field(default_factory=list)


@dataclass
class RainLine:
    x: float
    y: float
    speed: float
    length: float
    alpha: int


class RainScene:
    def __init__(self, width: int, height: int, level='中雨', seed=None):
        if min(width, height) < 1:
            raise ValueError('雨幕画面尺寸无效')
        self.width, self.height = int(width), int(height)
        self.random = random.Random(seed)
        self.elapsed = 0.0
        self.level = ''
        self.set_level(level)

    def _drop(self, initial=False):
        radius = self.random.choices((3, 4, 5, 6, 8, 10, 12), (12, 18, 20, 18, 16, 10, 6))[0]
        return GlassDrop(self.random.uniform(0, self.width),
                         self.random.uniform(0, self.height) if initial else -radius*4,
                         radius, self.random.uniform(.2, 5),
                         self.random.uniform(12, 28)+radius*radius*1.8,
                         self.random.uniform(0, math.tau))

    def _line(self, initial=False):
        return RainLine(self.random.uniform(0, self.width),
                        self.random.uniform(0, self.height) if initial else -30,
                        self.random.uniform(120, 330), self.random.uniform(14, 36),
                        self.random.randint(40, 80))

    def set_level(self, level):
        level = level if level in RAIN_LEVELS else '中雨'
        if level == self.level:
            return
        self.level = level
        area = self.width*self.height/(1600*900)
        drops, lines = RAIN_LEVELS[level]
        self.drops = [self._drop(True) for _ in range(min(450, max(12, round(drops*area))))]
        self.lines = [self._line(True) for _ in range(min(260, max(8, round(lines*area))))]

    def frame(self, dt: float):
        dt = min(.12, max(0, dt))
        self.elapsed += dt
        image = Image.new('RGBA', (self.width, self.height))
        draw = ImageDraw.Draw(image)
        for index, line in enumerate(self.lines):
            line.y += line.speed*dt
            line.x -= line.speed*dt*.045
            if line.y > self.height+line.length or line.x < -20:
                line = self.lines[index] = self._line()
            draw.line((line.x+1.1, line.y-line.length, line.x, line.y),
                      fill=(207, 228, 243, line.alpha), width=1)
        for index, drop in enumerate(self.drops):
            drop.wait -= dt
            if drop.wait <= 0:
                if drop.trail:
                    drop.trail = [(x, y, age+dt) for x, y, age in drop.trail if age+dt < 2.4]
                drop.trail.append((drop.x, drop.y, 0.0))
                if len(drop.trail) > 45:
                    drop.trail.pop(0)
                drop.y += drop.speed*dt
                drop.x += math.sin(self.elapsed*1.3+drop.phase)*dt*2.8
                if drop.y > self.height+drop.radius*4:
                    drop = self.drops[index] = self._drop()
                elif self.random.random() < dt*.20:
                    drop.wait = self.random.uniform(.2, 1.1)
            trail = drop.trail
            for before, after in zip(trail, trail[1:]):
                alpha = round(48*max(0, 1-before[2]/2.4))
                draw.line((before[0], before[1], after[0], after[1]),
                          fill=(139, 173, 193, alpha), width=max(1, drop.radius//3))
                draw.line((before[0]-.6, before[1], after[0]-.6, after[1]),
                          fill=(224, 241, 250, alpha//2), width=1)
            sprite = water_drop(drop.radius)
            image.alpha_composite(sprite, (round(drop.x-sprite.width/2), round(drop.y-sprite.height/2)))
        return image


def premultiplied_bgra(image):
    # Pillow's native conversion avoids several full-desktop NumPy buffers.
    # RGBa is premultiplied alpha; BGRa matches the layered window's DIB.
    return image.convert('RGBA').convert('RGBa').tobytes('raw', 'BGRa')
