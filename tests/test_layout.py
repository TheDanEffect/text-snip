"""Checks that the shape of text survives being read.

No reader and no screen is involved: these feed the shape rebuilder the word
positions a reader would have reported, so a failure is always the rebuilding
and never the reading. Run it with:

    python tests/test_layout.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from text_snip import rebuild_shape, trim_blank_edges  # noqa: E402


class Box:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height


# ---------- laying text out the way a screen would ----------
CHAR, STEP, HEIGHT = 10.0, 20.0, 14.0           # a code font: every letter the same width
WIDE, THIN, SPACE, PSTEP, PHEIGHT = 11.0, 5.0, 4.5, 22.0, 15.0   # a normal font


def fixed_width(block):
    """Every character the same width, as a code editor draws it."""
    lines = []
    for row, raw in enumerate(block.split("\n")):
        words, column = [], 0
        for chunk in raw.split(" "):
            if chunk:
                words.append((Box(column * CHAR, row * STEP, len(chunk) * CHAR, HEIGHT), chunk))
            column += len(chunk) + 1
        if words:
            lines.append(words)
    return lines


def proportional(block):
    """Letters of different widths and a space narrower than a letter."""
    lines = []
    for row, raw in enumerate(block.split("\n")):
        words, pen = [], len(raw) - len(raw.lstrip(" "))
        pen *= SPACE
        for chunk in raw.strip(" ").split(" "):
            if not chunk:
                pen += SPACE
                continue
            width = sum(THIN if c in "ilftjr.,:;'!|" else WIDE for c in chunk)
            words.append((Box(pen, row * PSTEP, width, PHEIGHT), chunk))
            pen += width + SPACE
        if words:
            lines.append(words)
    return lines


# ---------- the checks ----------
results = []


def check(name, block, lay_out=fixed_width, expect=None):
    got = trim_blank_edges(rebuild_shape(lay_out(block)))
    want = trim_blank_edges(expect if expect is not None else block)
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print("--- wanted ---\n" + want + "\n--- got ---\n" + got)
    results.append(ok)


check("indented code", """
def read_text(img):
    scale = 3 if img.height < 150 else 1
    if scale > 1:
        img = img.resize((img.width, img.height))
    return img
""")

check("nested bullet list", """
Shopping
  - apples
  - bread
      - sourdough if they have it
  - milk
Done
""")

check("table columns", """
Name        Role            City
Dan         Developer       Cape Town
Thandi      Designer        Durban
""")

check("paragraphs separated by a blank line", """
This is the first paragraph and it runs
across two lines of text.

This is the second paragraph, set apart
by one blank line above it.
""")

check("aligned assignments", """
HOTKEY_MODS = 0x0002
HOTKEY_KEY  = 0x54
DIM         = 0.45
""")

# Only the indentation relative to the leftmost line is kept, not the margin the
# selection happened to start at.
check("a block indented as a whole keeps its relative shape", """
        if ready:
            go()
        else:
            wait()
""", expect="""
if ready:
    go()
else:
    wait()
""")

check("plain prose stays single spaced", """
The quick brown fox jumps over a lazy dog
and then it sits down to rest for a while.
""", proportional)

# This one needs the line step to be sane on its own: the only gap to measure is
# the doubled one, so measuring alone would read it as ordinary spacing.
check("a blank line between just two lines of prose", """
First paragraph of ordinary writing here.

Second paragraph after a blank line.
""", proportional)

check("indented quote inside prose", """
He wrote this down clearly:
    this part was indented by four
    and so was this line as well
then the text carried on as before.
""", proportional)

check("bullet list in a normal font", """
Things to buy
   - apples and pears
   - a loaf of bread
   - milk
""", proportional)

# A label and its value far apart are reported as two lines at the same height,
# and belong on one line of text.
got = rebuild_shape([[(Box(0, 0, 50, HEIGHT), "Total")], [(Box(300, 2, 40, HEIGHT), "R450")]])
ok = got == "Total" + " " * 25 + "R450"
print(f"{'PASS' if ok else 'FAIL'}  side by side lines merge onto one row")
if not ok:
    print(repr(got))
results.append(ok)

# Awkward input a real snip can produce: it must not raise.
for name, lines in [("nothing at all", []),
                    ("a line with no words", [[]]),
                    ("a single one-character word", [[(Box(5, 5, 9, HEIGHT), "x")]])]:
    try:
        rebuild_shape(lines)
        print(f"PASS  {name}")
        results.append(True)
    except Exception as error:
        print(f"FAIL  {name}: {type(error).__name__}: {error}")
        results.append(False)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
