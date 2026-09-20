#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    make_icon.py
# Description: Draw the Dashboards Plugin Store icon — the same house and the same
#              indigo as the web app's home-screen icon, on the Highsteads shape.
# Author:      CliveS & Claude Opus 5
# Date:        20-09-2026
# Version:     1.0
#
# Official requirement (indigo-reference/official/official-plugin-dev.md:391):
# Contents/Resources/icon.png, PNG, 256x256 optimal, never under 128px high.
#
# WHY IT DOES NOT USE THE HOUSE NAVY. The other Highsteads icons are dark blue, but
# Dashboards already HAS a mark: apple-touch-icon.png, a white house on #5856D6, which
# is what sits on the home screen of every phone that has the dashboards saved. An icon
# earns its keep by being recognised, so that mark wins and the house pattern supplies
# only the shape and the name beneath.
#
# The house geometry is MEASURED from apple-touch-icon-192.png by scanning its white
# runs, not eyeballed — roof apex 0.50/0.205, eaves 0.22-0.78 at 0.505, body
# 0.28-0.72, windows at 0.33-0.41 and 0.59-0.67, door 0.44-0.56. Keeping the two marks
# the same shape is the entire point, so they are reproduced rather than approximated.

from PIL import Image, ImageDraw, ImageFont

S     = 1024
SCALE = 4
IND_T = (96, 94, 221)              # a shade above #5856D6
IND_B = (80, 78, 207)              # and a shade below. Kept TIGHT: the source is flat,
                                   # and a wide gradient stops reading as the same purple.
WHITE = (255, 255, 255)
EDGE  = (128, 126, 236)

BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def background():
    bg = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / (S - 1)
        d.line([(0, y), (S, y)],
               fill=tuple(int(a + (b - a) * t) for a, b in zip(IND_T, IND_B)))
    return bg


# The glyph is 0.59 of the source square wide and 0.655 tall, so its own aspect is
# 0.90. Scaling width and height independently is what turned the first attempt from a
# squat house into a tall narrow one that read as a letter H — derive one from the
# other rather than picking both.
HOUSE_ASPECT = 0.59 / 0.655


def house(house_w, top):
    """The measured glyph, as a mask: roof and body drawn, windows and door cut out."""
    width  = house_w / 0.59
    height = house_w / HOUSE_ASPECT
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)

    def X(f):
        return (S - width) / 2 + f * width

    def Y(f):
        # the source runs from 0.205 (apex) to 0.86 (foot); map that onto top..top+height
        return top + (f - 0.205) / (0.86 - 0.205) * height

    d.polygon([(X(0.50), Y(0.205)), (X(0.205), Y(0.515)), (X(0.795), Y(0.515))], fill=255)
    d.rectangle([X(0.28), Y(0.495), X(0.72), Y(0.86)], fill=255)
    for a, b in ((0.335, 0.415), (0.585, 0.665)):                       # windows
        d.rectangle([X(a), Y(0.555), X(b), Y(0.655)], fill=0)
    d.rectangle([X(0.44), Y(0.655), X(0.56), Y(0.87)], fill=0)          # doorway
    return m


def draw():
    img = background()

    glyph = Image.new("RGB", (S, S), WHITE)
    img.paste(glyph, (0, 0), house(house_w=470, top=150))

    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(BOLD, 98)
    text, spacing = "DASHBOARDS", 5
    widths = [d.textbbox((0, 0), c, font=f)[2] for c in text]
    x = (S - (sum(widths) + spacing * (len(text) - 1))) / 2
    for c, w in zip(text, widths):
        d.text((x, 762), c, font=f, fill=WHITE)
        x += w + spacing

    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], 196, fill=255)
    out.paste(img, (0, 0), mask)
    ImageDraw.Draw(out).rounded_rectangle([6, 6, S - 7, S - 7], 190,
                                          outline=EDGE + (255,), width=10)
    return out.resize((S // SCALE, S // SCALE), Image.LANCZOS)


if __name__ == "__main__":
    import sys
    draw().save(sys.argv[1])
    print("written:", sys.argv[1])
