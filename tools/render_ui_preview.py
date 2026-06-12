"""Render a desktop preview of the 128x296 monochrome firmware layout."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 128, 296
OUT = Path(__file__).resolve().parents[1] / "preview"
FONT = Path(r"C:\Windows\Fonts\arialbd.ttf")


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)


def canvas():
    image = Image.new("1", (W, H), 1)
    return image, ImageDraw.Draw(image)


def centered(draw, y, value, size):
    f = font(size)
    box = draw.textbbox((0, 0), value, font=f)
    draw.text(((W - box[2]) // 2, y), value, font=f, fill=0)


def header(draw, left, right):
    draw.ellipse((7, 7, 21, 21), fill=0)
    draw.text((27, 7), left, font=font(15), fill=0)
    right_font = font(8 if left == "SCROLL" else 12)
    rb = draw.textbbox((0, 0), right, font=right_font)
    draw.text((W - rb[2] - 6, 11 if left == "SCROLL" else 9),
              right, font=right_font, fill=0)
    draw.line((5, 30, 122, 30), fill=0, width=1)


def footer(draw, scroll=False):
    draw.rounded_rectangle((6, 260 if not scroll else 263, 121, 290),
                           radius=7, outline=0, width=1)
    if scroll:
        draw.ellipse((12, 270, 24, 282), outline=0, width=2)
        draw.text((31, 270), "BUTTON RETURNS", font=font(7), fill=0)
        draw.text((49, 280), "TO INFO", font=font(7), fill=0)
    else:
        draw.ellipse((12, 265, 22, 275), outline=0, width=2)
        draw.text((27, 264), "KNOB FLICK PAGE", font=font(7), fill=0)
        draw.ellipse((13, 278, 21, 286), fill=0)
        draw.text((27, 276), "BUTTON MODE", font=font(7), fill=0)


def cloud(draw, cx, cy):
    draw.arc((cx - 23, cy - 6, cx - 5, cy + 12), 120, 300, fill=0, width=3)
    draw.arc((cx - 14, cy - 16, cx + 12, cy + 10), 175, 350, fill=0, width=3)
    draw.arc((cx + 5, cy - 6, cx + 23, cy + 12), 220, 60, fill=0, width=3)
    draw.line((cx - 19, cy + 12, cx + 19, cy + 12), fill=0, width=3)


def clock_page():
    im, d = canvas()
    header(d, "INFO", "1/2")
    centered(d, 39, "14:36", 36)
    centered(d, 82, "WED 06/10", 14)
    d.rounded_rectangle((6, 106, 121, 287), radius=10, outline=0, width=2)
    centered(d, 115, "FRANKFURT", 13)
    cloud(d, 64, 160)
    centered(d, 187, "CLOUDY", 10)
    d.line((14, 205, 114, 205), fill=0)
    centered(d, 213, "18 C", 27)
    centered(d, 260, "72%  WIND 3", 9)
    return im


def icon_label(draw, y, label, value):
    draw.rounded_rectangle((6, y, 121, y + 39), radius=8, outline=0)
    draw.rectangle((13, y + 9, 31, y + 27), outline=0, width=2)
    draw.text((42, y + 9), label, font=font(14), fill=0)
    vb = draw.textbbox((0, 0), value, font=font(12))
    draw.text((116 - vb[2], y + 11), value, font=font(12), fill=0)


def bar(draw, y, value):
    draw.rounded_rectangle((13, y, 115, y + 10), radius=5, outline=0, width=2)
    draw.rounded_rectangle((15, y + 2, 15 + int(98 * value), y + 8),
                           radius=3, fill=0)


def pc_page():
    im, d = canvas()
    header(d, "INFO", "2/3")
    centered(d, 37, "PC STATUS", 17)

    d.rounded_rectangle((6, 61, 121, 113), radius=8, outline=0)
    d.rectangle((13, 70, 31, 88), outline=0, width=2)
    d.text((40, 68), "CPU", font=font(14), fill=0)
    value_font = font(14)
    vb = d.textbbox((0, 0), "38%", font=value_font)
    d.text((116 - vb[2], 68), "38%", font=value_font, fill=0)
    bar(d, 96, .38)

    d.rounded_rectangle((6, 117, 121, 152), radius=8, outline=0)
    d.ellipse((15, 124, 27, 143), outline=0, width=2)
    d.text((40, 124), "TEMP", font=font(14), fill=0)
    vb = d.textbbox((0, 0), "82 C", font=value_font)
    d.text((116 - vb[2], 124), "82 C", font=value_font, fill=0)

    d.rounded_rectangle((6, 156, 121, 225), radius=8, outline=0)
    d.rectangle((13, 164, 31, 182), outline=0, width=2)
    d.text((40, 162), "MEMORY", font=font(14), fill=0)
    memory_value = "12 / 16 GB"
    vb = d.textbbox((0, 0), memory_value, font=value_font)
    d.text((116 - vb[2], 185), memory_value, font=value_font, fill=0)
    bar(d, 207, .75)

    d.rounded_rectangle((6, 229, 121, 281), radius=8, outline=0)
    d.arc((12, 236, 32, 256), 205, 335, fill=0, width=2)
    d.text((42, 235), "NETWORK", font=font(14), fill=0)
    centered(d, 257, "UFI E8D3", 14)
    return im


def arrow(draw, y, up):
    if up:
        draw.polygon((64, y, 55, y + 12, 60, y + 12, 60, y + 26,
                      68, y + 26, 68, y + 12, 73, y + 12), fill=0)
    else:
        draw.polygon((60, y, 68, y, 68, y + 14, 73, y + 14, 64, y + 26,
                      55, y + 14, 60, y + 14), fill=0)


def scroll_page():
    im, d = canvas()
    header(d, "SCROLL", "MODE")
    arrow(d, 42, True)
    d.ellipse((20, 82, 108, 170), outline=0, width=3)
    d.ellipse((42, 104, 86, 148), outline=0)
    d.ellipse((52, 114, 76, 138), fill=0)
    arrow(d, 178, False)
    centered(d, 211, "MOUSE WHEEL", 15)
    d.line((27, 232, 101, 232), fill=0)
    centered(d, 239, "INERTIA FEEL", 9)
    footer(d, True)
    return im


def main():
    OUT.mkdir(exist_ok=True)
    pages = [
        ("clock-weather", clock_page()),
        ("pc-status", pc_page()),
        ("scroll-control", scroll_page()),
    ]
    sheet = Image.new("L", (W * 3 + 32, H + 16), 255)
    for index, (name, image) in enumerate(pages):
        image.resize((W * 4, H * 4), Image.Resampling.NEAREST).save(
            OUT / f"{name}.png"
        )
        sheet.paste(image.convert("L"), (8 + index * (W + 8), 8))
    sheet.resize((sheet.width * 3, sheet.height * 3),
                 Image.Resampling.NEAREST).save(OUT / "ui-overview.png")


if __name__ == "__main__":
    main()
