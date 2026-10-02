"""text-snip: press Ctrl+Alt+T, drag a box over any text on screen, and the text
is copied to the clipboard and appended to a monthly notes file.

Runs quietly in the background. Uses the OCR engine built into Windows 10/11.
"""

import asyncio
import csv
import ctypes
import ctypes.wintypes as wt
import datetime
import functools
import io
import queue
import shutil
import subprocess
import sys
import threading
import traceback
from collections import namedtuple
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageEnhance, ImageGrab, ImageOps, ImageTk

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ---------- settings ----------
HOTKEY_MODS = 0x0002 | 0x0001 | 0x4000  # Ctrl + Alt, ignore key auto-repeat
HOTKEY_KEY = 0x54                       # T
DIM = 0.45                              # how dark the screen gets (0 = black, 1 = normal)


def documents_folder():
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # 5 = My Documents
    return Path(buf.value or Path.home() / "Documents")


NOTES_DIR = documents_folder() / "text-snips"


def log_error():
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    with open(NOTES_DIR / "text-snip-errors.log", "a", encoding="utf-8") as f:
        f.write(f"\n--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
        f.write(traceback.format_exc())


# ---------- hotkey (runs on its own thread, sleeps until the key is pressed) ----------
def listen_for_hotkey(events):
    if not user32.RegisterHotKey(None, 1, HOTKEY_MODS, HOTKEY_KEY):
        events.put("hotkey-taken")
        return
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == 0x0312:  # WM_HOTKEY
            events.put("snip")


# ---------- clipboard ----------
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p


def copy_to_clipboard(text):
    data = text.encode("utf-16-le") + b"\x00\x00"
    for _ in range(10):  # another app may briefly hold the clipboard
        if user32.OpenClipboard(None):
            break
        threading.Event().wait(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ctypes.memmove(kernel32.GlobalLock(handle), data, len(data))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(13, handle)  # CF_UNICODETEXT
        return True
    finally:
        user32.CloseClipboard()


# ---------- shape ----------
# A reader reports words, not the spaces between them, so simply joining the
# words throws away the shape of the text: indentation, aligned columns and
# paragraph breaks all collapse. Every reader does say where each word sat on
# screen, though, so the shape can be measured back out of those positions. This
# works the same for code, bullet lists, tables and prose, because it only looks
# at where words are, never at what they say.

def median(values):
    values = sorted(values)
    if not values:
        return 0.0
    middle = len(values) // 2
    if len(values) % 2:
        return float(values[middle])
    return (values[middle - 1] + values[middle]) / 2


def character_advance(words):
    """How far the text moves along per character, fitted across every word.

    A reader draws its boxes tight around the letters, so a box is narrower than
    the space the word really occupies, and the gap between two boxes is wider
    than the space that separates them. Measuring either one directly gets the
    answer wrong. Fitting width against letter count over many words cancels the
    tight edges out, because they add the same small amount to every box.
    """
    counts = [(len(text), box.width) for box, text in words if len(text) > 1]
    if len(counts) < 2:
        return None
    total = len(counts)
    sum_n = sum(n for n, _ in counts)
    sum_w = sum(w for _, w in counts)
    spread = total * sum(n * n for n, _ in counts) - sum_n * sum_n
    if not spread:
        return None
    advance = (total * sum(n * w for n, w in counts) - sum_n * sum_w) / spread
    return advance if advance > 0 else None


def on_character_grid(rows, advance):
    """Lay the words out on a fixed character grid, or return None.

    Code is written in a font where every character is the same width, so once
    that width is known each word's column can be read straight off its position
    and both the indentation and the spacing come out exactly right. Returns one
    finished line of text per row, or None when the words do not line up on a
    grid, which is how ordinary writing behaves.
    """
    left = min(box.x for row in rows for box, _ in row)
    columns = [(box.x - left) / advance for row in rows for box, _ in row]
    drift = sum(min(c % 1, 1 - c % 1) for c in columns) / len(columns)
    if drift > 0.18:
        return None
    out = []
    for row in rows:
        text = ""
        for box, word in row:
            column = round((box.x - left) / advance)
            if text and column < len(text) + 1:
                return None  # words would collide, so this is not really a grid
            text += " " * (column - len(text)) + word
        out.append(text)
    return out


def rebuild_shape(lines):
    """lines is a list of lines, each a list of (box, word) pairs, where a box
    has x, y, width and height in pixels. Both readers below produce that."""
    rows = [sorted(line, key=lambda pair: pair[0].x) for line in lines if line]
    if not rows:
        return ""
    every = [pair for row in rows for pair in row]

    advance = character_advance(every) or median([r.width for r, _ in every]) or 8.0
    # The narrowest gaps on screen are the single spaces, so read the space from
    # those rather than from the average: in a table every gap is a wide one, and
    # an average would quietly stretch every column out of line. A space is never
    # wider than one character, which catches a table that has no single spaces
    # in it at all.
    gaps = sorted(b.x - (a.x + a.width)
                  for row in rows for (a, _), (b, _) in zip(row, row[1:]))
    narrow = [g for g in gaps if g > advance * 0.15]
    space = min(narrow[len(narrow) // 5] if narrow else advance, advance)
    space = max(space, advance * 0.25)
    line_height = median([r.height for r, _ in every]) or advance * 2

    # Two lines that overlap vertically are side by side on screen rather than
    # above each other: table columns, or a label and its value. They belong on
    # one line of text, in left-to-right order.
    rows.sort(key=lambda row: median([r.y + r.height / 2 for r, _ in row]))
    merged = []
    for row in rows:
        middle = median([r.y + r.height / 2 for r, _ in row])
        if merged and abs(middle - merged[-1][0]) < line_height * 0.5:
            merged[-1][1].extend(row)
            merged[-1][1].sort(key=lambda pair: pair[0].x)
        else:
            merged.append([middle, list(row)])

    # Code sits on a fixed grid of characters, which gives an exact answer, so
    # try that first and only measure the gaps when the text is not on a grid.
    gridded = on_character_grid([row for _, row in merged], advance)

    # Group the left edges into indent levels. A reader wobbles by a few pixels,
    # and without this two lines indented the same amount come out different.
    left = min(row[0][0].x for _, row in merged)
    levels = []
    for edge in sorted(row[0][0].x for _, row in merged):
        if not levels or edge - levels[-1][0] >= space * 0.75:
            levels.append((edge, max(0, round((edge - left) / space))))

    def indent_at(x):
        return max(depth for edge, depth in levels if edge <= x + space * 0.75)

    # How far apart lines normally sit, so that a bigger jump can be read as one
    # or more blank lines. The closest lines are the ones with nothing between
    # them, and a line is never spaced far from the height of its own text:
    # together that keeps a two-line snip from reading its one blank line as
    # ordinary spacing and losing the paragraph break.
    steps = sorted(b[0] - a[0] for a, b in zip(merged, merged[1:]))
    steps = [s for s in steps if s > 0]
    step = steps[len(steps) // 5] if steps else line_height * 1.35
    step = min(max(step, line_height * 1.05), line_height * 1.8)

    out = []
    previous = None
    for number, (middle, row) in enumerate(merged):
        if previous is not None:
            blanks = round((middle - previous) / step) - 1
            out.extend([""] * min(max(blanks, 0), 2))
        previous = middle
        if gridded is not None:
            out.append(gridded[number].rstrip())
            continue
        text = " " * indent_at(row[0][0].x)
        for index, (rect, word) in enumerate(row):
            if index:
                before = row[index - 1][0]
                gap = rect.x - (before.x + before.width)
                # One space unless the gap is clearly wider, which is what keeps
                # columns lined up. Capped so a stray word far right cannot
                # produce a line hundreds of characters long.
                spaces = round(gap / space) if gap > space * 1.8 else 1
                text += " " * min(max(spaces, 1), 40)
            text += word
        out.append(text.rstrip())
    return "\n".join(out)


def trim_blank_edges(text):
    # Drops empty lines at the top and bottom without touching the indentation
    # of the lines that are kept.
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


# ---------- reading the text ----------
# Two readers, tried in this order:
#
# Tesseract reads what is actually on screen, character by character. On a
# benchmark of rendered code at six sizes and both themes it scored 0.99 out of
# 1.0, and is the reason code comes out right.
#
# Windows' own reader needs nothing installed, so it stands in when Tesseract is
# missing. It is built for reading sentences and runs a dictionary over its
# guesses, which suits ordinary writing but mangles code: on the same benchmark
# it scored 0.66, turning plt into pit, 0 into e, and quietly dropping pieces of
# a line. The README says so, because a wrong snip looks just like a right one.

Box = namedtuple("Box", "x y width height")

NO_WINDOW = 0x08000000  # keeps a console from flashing up, since this runs windowless


def enlarge(img, scale):
    if scale <= 1:
        return img
    return img.resize((img.width * scale, img.height * scale), Image.LANCZOS)


def fit_scale(img, wanted):
    # Enlarging helps, but a huge image is slow and can be refused outright.
    while wanted > 1 and max(img.width, img.height) * wanted > 9000:
        wanted -= 1
    return wanted


@functools.lru_cache(maxsize=1)
def tesseract_path():
    """Where Tesseract is installed, or None. Looked up once."""
    found = shutil.which("tesseract")
    if found:
        return found
    for folder in (r"C:\Program Files\Tesseract-OCR", r"C:\Program Files (x86)\Tesseract-OCR",
                   Path.home() / r"AppData\Local\Programs\Tesseract-OCR"):
        candidate = Path(folder) / "tesseract.exe"
        if candidate.exists():
            return str(candidate)
    return None


def read_with_tesseract(img):
    """Returns lines of (box, word), or None if Tesseract is not usable."""
    exe = tesseract_path()
    if not exe:
        return None

    # Tesseract reads plain light-on-dark best, so flatten the syntax colouring,
    # turn a dark theme the right way up, and stretch the contrast.
    grey = img.convert("L")
    shades = sorted(grey.resize((48, 48)).getdata())
    if shades[len(shades) // 2] < 128:  # a dark background
        grey = ImageOps.invert(grey)
    grey = enlarge(ImageOps.autocontrast(grey), fit_scale(grey, 3))

    data = io.BytesIO()
    grey.save(data, format="PNG")
    # psm 6 means "one block of text written in lines", which is what a snip is.
    done = subprocess.run(
        [exe, "-", "stdout", "--psm", "6", "tsv"],
        input=data.getvalue(), capture_output=True, creationflags=NO_WINDOW,
    )
    if done.returncode != 0:
        return None

    report = done.stdout.decode("utf-8", "replace")
    lines = {}
    for word in csv.DictReader(io.StringIO(report), delimiter="\t", quoting=csv.QUOTE_NONE):
        if word.get("level") != "5" or not (word.get("text") or "").strip():
            continue
        where = (int(word["block_num"]), int(word["par_num"]), int(word["line_num"]))
        box = Box(int(word["left"]), int(word["top"]), int(word["width"]), int(word["height"]))
        lines.setdefault(where, []).append((box, word["text"]))
    return [lines[key] for key in sorted(lines)]


async def _windows_lines(img):
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    writer = DataWriter()
    writer.write_bytes(img.tobytes())
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.RGBA8, img.width, img.height
    )
    engine = OcrEngine.try_create_from_user_profile_languages()
    result = await engine.recognize_async(bitmap)
    return [[(word.bounding_rect, word.text) for word in line.words] for line in result.lines]


def read_with_windows(img):
    # This reader did measurably worse on every kind of cleaning up that helped
    # Tesseract, so it gets the picture as captured, only enlarged.
    scale = fit_scale(img, 3 if img.height < 150 else 2 if img.height < 600 else 1)
    return asyncio.run(_windows_lines(enlarge(img, scale).convert("RGBA")))


def read_text(img):
    lines = None
    try:
        lines = read_with_tesseract(img)
    except Exception:
        log_error()  # fall through to the reader that is always there
    if not lines:
        lines = read_with_windows(img)
    return trim_blank_edges(rebuild_shape(lines))


# ---------- saving ----------
def save_note(text):
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    with open(NOTES_DIR / f"{now:%Y-%m}.md", "a", encoding="utf-8") as f:
        f.write(f"## {now:%Y-%m-%d %H:%M}\n\n{text}\n\n")


# ---------- the dimmed selection screen ----------
class SnipApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.events = queue.Queue()
        self.overlay = None
        threading.Thread(target=listen_for_hotkey, args=(self.events,), daemon=True).start()
        self.root.after(200, self.check_events)

    def check_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event == "snip" and self.overlay is None:
                    self.open_overlay()
                elif event == "hotkey-taken":
                    self.toast("Ctrl+Alt+T is already in use.\ntext-snip could not start.", 4000)
                    self.root.after(4200, self.root.destroy)
        except queue.Empty:
            pass
        self.root.after(200, self.check_events)

    def open_overlay(self):
        left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        self.shot = ImageGrab.grab(all_screens=True)  # frozen copy, so videos stop moving
        self.origin = (left, top)

        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.geometry(f"{width}x{height}{left:+d}{top:+d}")
        self.overlay.attributes("-topmost", True)

        self.canvas = tk.Canvas(self.overlay, cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.dim_photo = ImageTk.PhotoImage(ImageEnhance.Brightness(self.shot).enhance(DIM))
        self.canvas.create_image(0, 0, image=self.dim_photo, anchor="nw")
        self.bright = self.canvas.create_image(0, 0, anchor="nw")
        self.box = self.canvas.create_rectangle(0, 0, 0, 0, outline="white", width=2)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.overlay.bind("<Escape>", lambda e: self.close_overlay())
        self.canvas.bind("<ButtonPress-3>", lambda e: self.close_overlay())
        self.overlay.focus_force()

    def on_press(self, e):
        self.start = (e.x, e.y)

    def selection(self, e):
        x1, y1 = self.start
        return min(x1, e.x), min(y1, e.y), max(x1, e.x), max(y1, e.y)

    def on_drag(self, e):
        box = self.selection(e)
        self.canvas.coords(self.box, *box)
        if box[2] - box[0] > 1 and box[3] - box[1] > 1:
            self.bright_photo = ImageTk.PhotoImage(self.shot.crop(box))
            self.canvas.itemconfigure(self.bright, image=self.bright_photo)
            self.canvas.coords(self.bright, box[0], box[1])

    def on_release(self, e):
        box = self.selection(e)
        crop = self.shot.crop(box)
        cursor = (e.x + self.origin[0], e.y + self.origin[1])
        self.close_overlay()
        if box[2] - box[0] < 5 or box[3] - box[1] < 5:
            return
        self.root.update()  # let the overlay disappear before reading
        try:
            text = read_text(crop)
        except Exception:
            log_error()
            self.toast("Something went wrong reading the text.", at=cursor)
            return
        if not text:
            self.toast("No text found", at=cursor)
            return
        copy_to_clipboard(text)
        save_note(text)
        self.toast(f"Copied ✓  ({len(text)} characters)", at=cursor)

    def close_overlay(self):
        if self.overlay is not None:
            self.overlay.destroy()
        self.overlay = self.shot = self.dim_photo = self.bright_photo = None

    def toast(self, message, ms=1500, at=None):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        tk.Label(win, text=message, bg="#222", fg="white", padx=12, pady=6,
                 font=("Segoe UI", 10)).pack()
        x, y = at if at else (self.root.winfo_screenwidth() // 2 - 120, 40)
        win.geometry(f"+{x + 12}+{y + 12}")
        win.after(ms, win.destroy)

    def run(self):
        self.root.mainloop()


def main():
    # Only one copy may run at a time.
    kernel32.CreateMutexW(None, False, "text-snip-single-instance")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
    # Use real pixels so the selection lines up on scaled (e.g. 125%) displays.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()
    try:
        SnipApp().run()
    except Exception:
        log_error()
        raise


if __name__ == "__main__":
    main()
