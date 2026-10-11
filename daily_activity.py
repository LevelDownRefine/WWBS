"""Read the yellow current activity counter without matching its background."""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image


def _yellow_digits(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert('RGB')).astype(np.int16)
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    return (red > 155) & (green > 130) & (blue < green*.85) & (red > blue+35)


def _digits(mask: np.ndarray, minimum_height: float, maximum_height: float):
    columns = np.flatnonzero(mask.sum(axis=0) >= 2)
    if not len(columns):
        return []
    parts = []
    for group in np.split(columns, np.flatnonzero(np.diff(columns) > 2)+1):
        left, right = int(group[0]), int(group[-1])+1
        ys = np.flatnonzero(mask[:, left:right].any(axis=1))
        if not len(ys):
            continue
        top, bottom = int(ys[0]), int(ys[-1])+1
        height, width = bottom-top, right-left
        if minimum_height <= height <= maximum_height and .25 <= width/height <= 1.1:
            parts.append((left, top, right, bottom, mask[top:bottom, left:right]))
    return parts


def _normalized(mask: np.ndarray) -> np.ndarray:
    return np.asarray(Image.fromarray(mask.astype(np.uint8)*255).resize(
        (24, 36), Image.Resampling.BILINEAR)) > 100


@lru_cache(maxsize=8)
def _reference_digits(template: str, modified_ns: int):
    with Image.open(template) as image:
        parts = _digits(_yellow_digits(image), 10, image.height)
    if len(parts) != 3:
        raise ValueError('活跃度100模板没有完整的三个数字。')
    return tuple(_normalized(part[4]) for part in parts)


def activity_counter_full(screenshot: Path, template: Path) -> bool:
    with Image.open(screenshot) as image:
        width, height = image.size
        # Milestone labels (including another "100") are outside this region.
        region = image.crop((round(width*.15), round(height*.77),
                             round(width*.29), round(height*.94)))
        parts = _digits(_yellow_digits(region), height*.020, height*.052)
    try:
        reference = _reference_digits(str(template), template.stat().st_mtime_ns)
    except (OSError, ValueError):
        return False
    for index in range(max(0, len(parts)-2)):
        candidate = parts[index:index+3]
        heights = [part[3]-part[1] for part in candidate]
        if max(heights)-min(heights) > max(3, height*.005):
            continue
        if max(part[1] for part in candidate)-min(part[1] for part in candidate) > max(3, height*.005):
            continue
        if any(not 0 < following[0]-current[2] < max(heights)*.65
               for current, following in zip(candidate, candidate[1:])):
            continue
        # The leading "1" must be narrow; a lone "0" or "80" cannot count.
        if (candidate[0][2]-candidate[0][0])/heights[0] > .55:
            continue
        matched = True
        for part, expected in zip(candidate, reference):
            actual = _normalized(part[4])
            overlap = np.logical_and(actual, expected).sum()
            union = np.logical_or(actual, expected).sum()
            if not union or overlap/union < .65:
                matched = False
                break
        if matched:
            return True
    return False
