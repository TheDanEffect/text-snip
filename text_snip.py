"""text-snip: press Ctrl+Alt+T, drag a box over any text on screen, and the text
is copied to the clipboard and appended to a monthly notes file.

Runs quietly in the background. Uses the OCR engine built into Windows 10/11.
"""

import asyncio
import ctypes
import ctypes.wintypes as wt
import datetime
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageEnhance, ImageGrab, ImageTk

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


# ---------- OCR ----------
async def _recognize(img):
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
    return "\n".join(line.text for line in result.lines)


def read_text(img):
    # Small text reads much better when enlarged first.
    scale = 3 if img.height < 150 else 2 if img.height < 600 else 1
    largest = max(img.width, img.height) * scale
    if largest > 9000:
        scale = max(1, 9000 // max(img.width, img.height))
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    return asyncio.run(_recognize(img.convert("RGBA"))).strip()


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
