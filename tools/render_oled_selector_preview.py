"""Render the 32x128 OLED three-position selector preview."""

from pathlib import Path

from PIL import Image, ImageDraw

W, H = 32, 128
OUT = Path(__file__).resolve().parents[1] / "preview" / "oled-selector.png"


def forecast_icon(draw: ImageDraw.ImageDraw, x: int, y: int, inverse: bool) -> None:
    color = 255 if inverse else 0
    draw.ellipse((x + 2, y + 1, x + 10, y + 9), outline=color, width=2)
    draw.line((x + 6, y - 1, x + 6, y + 1), fill=color)
    draw.line((x, y + 5, x + 2, y + 5), fill=color)
    draw.arc((x + 4, y + 8, x + 14, y + 18), 130, 330, fill=color, width=2)
    draw.arc((x + 9, y + 5, x + 20, y + 18), 170, 350, fill=color, width=2)
    draw.arc((x + 15, y + 9, x + 23, y + 18), 210, 50, fill=color, width=2)
    draw.line((x + 7, y + 18, x + 20, y + 18), fill=color, width=2)
    draw.line((x + 9, y + 21, x + 8, y + 24), fill=color, width=2)
    draw.line((x + 15, y + 21, x + 14, y + 24), fill=color, width=2)


def clock_icon(draw: ImageDraw.ImageDraw, x: int, y: int, inverse: bool) -> None:
    color = 255 if inverse else 0
    draw.ellipse((x + 2, y + 1, x + 20, y + 19), outline=color, width=2)
    draw.line((x + 11, y + 5, x + 11, y + 11), fill=color, width=2)
    draw.line((x + 11, y + 11, x + 16, y + 14), fill=color, width=2)
    draw.point((x + 11, y + 11), fill=color)


def computer_icon(draw: ImageDraw.ImageDraw, x: int, y: int, inverse: bool) -> None:
    color = 255 if inverse else 0
    draw.rectangle((x + 1, y + 2, x + 21, y + 16), outline=color, width=2)
    draw.line((x + 8, y + 18, x + 14, y + 18), fill=color, width=2)
    draw.line((x + 11, y + 16, x + 11, y + 20), fill=color, width=2)


def main() -> None:
    image = Image.new("1", (W, H), 1)
    draw = ImageDraw.Draw(image)
    slots = [(2, 2), (2, 49), (2, 96)]

    for index, (x, y) in enumerate(slots):
        selected = index == 1
        if selected:
            draw.rounded_rectangle((x, y, x + 27, y + 29), radius=7, fill=0)
        else:
            draw.rounded_rectangle((x, y, x + 27, y + 29), radius=7, outline=0)

    forecast_icon(draw, 5, 6, False)
    clock_icon(draw, 5, 54, True)
    computer_icon(draw, 5, 101, False)

    OUT.parent.mkdir(exist_ok=True)
    image.resize((W * 5, H * 5), Image.Resampling.NEAREST).save(OUT)


if __name__ == "__main__":
    main()
