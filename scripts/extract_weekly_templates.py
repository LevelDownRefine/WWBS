"""Extract CV reference crops, without altering the original screenshots."""
import argparse
from pathlib import Path
from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("home", type=Path)
    parser.add_argument("weekly", type=Path)
    parser.add_argument("--claimable", type=Path)
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "templates" / "weekly"
    output.mkdir(parents=True, exist_ok=True)
    crops = (
        (args.result, "cap_result.png", (1448, 649, 1601, 683)),
        (args.result, "return_home.png", (1210, 936, 1340, 972)),
        (args.home, "cap_home.png", (137, 240, 285, 272)),
        (args.home, "park_title.png", (158, 98, 413, 141)),
        (args.weekly, "weekly_tab.png", (585, 163, 693, 194)),
        (args.weekly, "claimed.png", (689, 983, 735, 1016)),
    )
    for source, name, box in crops:
        with Image.open(source) as image:
            if image.width != 1920 or image.height not in (1119, 1120):
                raise ValueError("References must be the supplied window screenshots")
            image.crop(box).convert("RGB").save(output / name)
    if args.claimable:
        with Image.open(args.claimable) as image:
            if image.size != (1606, 880):
                raise ValueError("Glowing chest reference must be the supplied 1606x880 crop")
            # The reference is cropped and scaled: its chest spacing is 209px,
            # compared with 214px in the 1920x1080 client.
            image.crop((428, 821, 484, 857)).convert("RGB").resize(
                (57, 37), Image.Resampling.LANCZOS).save(output / "claimable.png")


if __name__ == "__main__":
    main()
