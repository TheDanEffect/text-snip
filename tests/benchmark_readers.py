"""Scores how well each reader does on text whose exact wording is known.

Code is drawn the way an editor draws it, in a code font with syntax colouring,
in both a dark and a light theme and at several sizes. Each reader gets the same
pictures, and the result is compared with the text that went in. Run it with:

    python tests/benchmark_readers.py

Measured on 2026-10-02 with Tesseract 5.4: Tesseract scored 0.99 and Windows'
own reader 0.66. The gap is why Tesseract is worth installing. Windows' reader
is built for sentences and runs a dictionary over its guesses, so on code it
turns plt into pit, 0 into e, and silently drops pieces of a line.
"""
import difflib
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from text_snip import read_with_tesseract, read_with_windows, rebuild_shape  # noqa: E402

CODE_FONT = r"C:\Windows\Fonts\consola.ttf"
PROSE_FONT = r"C:\Windows\Fonts\segoeui.ttf"

CODE = """import matplotlib.pyplot as plt
import numpy as np

fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(x, y, label="loss", linewidth=1.5)
ax.set_xlabel("epoch")
plt.tight_layout()
plt.savefig("out.png", dpi=300)

for i, (key, value) in enumerate(items):
    if value is not None and i % 2 == 0:
        total += value * 0.5
    elif key in {"a", "b"}:
        counts[key] = counts.get(key, 0) + 1"""

PROSE = """Shopping list for the weekend

    - apples and pears
    - a loaf of sourdough bread
    - milk, the full cream one

Remember the market closes at four, so leave
before three if the traffic looks bad again.

Total        R450
Paid         R200
Owing        R250"""

# Roughly the colours VS Code uses in its default themes.
DARK = {"bg": (30, 30, 30), "text": (212, 212, 212), "keyword": (197, 134, 192),
        "string": (206, 145, 120), "number": (181, 206, 168)}
LIGHT = {"bg": (255, 255, 255), "text": (0, 0, 0), "keyword": (175, 0, 219),
         "string": (163, 21, 21), "number": (9, 134, 88)}
KEYWORDS = {"import", "as", "for", "in", "if", "is", "not", "and", "None", "elif", "return"}
TOKEN = re.compile(r'"[^"]*"|\w+|\s+|.')


def colour_of(token, theme):
    if token.startswith('"'):
        return theme["string"]
    if token in KEYWORDS:
        return theme["keyword"]
    if re.fullmatch(r"\d[\d.]*", token):
        return theme["number"]
    return theme["text"]


def draw(block, size, theme, font_path, colour=True, pad=12):
    font = ImageFont.truetype(font_path, size)
    lines = block.split("\n")
    step = round(size * 1.5)
    width = pad * 2 + max(round(font.getlength(line)) for line in lines)
    img = Image.new("RGB", (width, pad * 2 + step * len(lines)), theme["bg"])
    pen = ImageDraw.Draw(img)
    for row, line in enumerate(lines):
        if not colour:
            pen.text((pad, pad + row * step), line, font=font, fill=theme["text"])
            continue
        x = float(pad)
        for token in TOKEN.findall(line):
            if token.strip():
                pen.text((x, pad + row * step), token, font=font, fill=colour_of(token, theme))
            x += font.getlength(token)
    return img


def flatten(text):
    """Wording only, ignoring the shape, so legibility is scored on its own."""
    return "\n".join(" ".join(line.split()) for line in text.split("\n") if line.strip())


def indent_of(line):
    return len(line) - len(line.lstrip())


def report(name, want, picture):
    row = f"  {name:22}"
    for reader in (read_with_tesseract, read_with_windows):
        try:
            lines = reader(picture)
            got = rebuild_shape(lines) if lines else ""
        except Exception as error:
            row += f"{type(error).__name__:>12}"
            continue
        legible = difflib.SequenceMatcher(None, flatten(want), flatten(got)).ratio()
        wanted, given = want.split("\n"), got.split("\n")
        shaped = sum(indent_of(a) == indent_of(b) for a, b in zip(wanted, given))
        row += f"{legible:9.3f} {shaped:2}/{len(wanted)}"
    print(row)


print("                                 tesseract      windows")
print("                              score  indents  score  indents")
print("code, dark theme")
for size in (12, 13, 16, 20):
    report(f"{size}px", CODE, draw(CODE, size, DARK, CODE_FONT))
print("code, light theme")
for size in (12, 13, 16, 20):
    report(f"{size}px", CODE, draw(CODE, size, LIGHT, CODE_FONT))
print("ordinary writing")
for label, theme, size in (("light 15px", LIGHT, 15), ("dark 18px", DARK, 18)):
    report(label, PROSE, draw(PROSE, size, theme, PROSE_FONT, colour=False))
print("\n'score' is wording only, 1.000 being word for word.")
print("'indents' counts the lines whose indentation came back right.")
