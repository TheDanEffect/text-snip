# text-snip

**Copy text from anything on your screen: YouTube videos, images, screenshots, PDFs, games.**

Press **Ctrl + Alt + T**, drag a box over the text, then press **Ctrl + V** anywhere to paste it.
Like the Windows Snipping Tool, but for text.

- The screen freezes and dims so you can grab text from a moving video
- **Indentation and columns come back the way they looked**, so code, bullet lists and
  tables paste in the right shape instead of collapsing into one flat block
- Text goes straight to your clipboard
- Every grab is also saved to a notes file, with the date and time
- Works offline. Nothing is uploaded anywhere
- Runs quietly in the background (about 40 MB of RAM) and starts with Windows

## Requirements

- Windows 10 or 11
- [Python 3.10 or newer](https://www.python.org/downloads/). During install, tick **"Add Python to PATH"**.
- [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) to read the text. Strongly
  recommended: without it the tool falls back to the reader built into Windows, which is
  fine for ordinary writing but poor at code. See [How well it reads](#how-well-it-reads).

## Install

1. Download this project: click the green **Code** button above, then **Download ZIP**, and unzip it
   somewhere permanent (for example `Documents\text-snip`).
2. Open the unzipped folder, click the address bar, type `powershell` and press Enter.
3. Install the packages it needs:
   ```
   pip install -r requirements.txt
   ```
4. Install Tesseract, the text reader:
   ```
   winget install -e --id UB-Mannheim.TesseractOCR
   ```
   You can also use the [installer](https://github.com/UB-Mannheim/tesseract/wiki) if you
   prefer. text-snip finds it automatically in the usual places.
5. Start it and make it start with Windows:
   ```
   powershell -ExecutionPolicy Bypass -File install-startup.ps1
   ```

Now press **Ctrl + Alt + T** and try it.

## How to use

| Action | What happens |
|---|---|
| **Ctrl + Alt + T** | Screen freezes and dims |
| Drag a box | The text inside is copied, and a "Copied ✓" note appears |
| **Esc** or right-click | Cancel |
| **Ctrl + V** | Paste the text anywhere |

Your grabs are saved in **Documents\text-snips**, one file per month (for example `2026-09.md`).
They're plain text files, so open them with Notepad.

## How well it reads

There are two readers. Tesseract is used when it is installed, and the reader built into
Windows stands in when it isn't. `tests/benchmark_readers.py` scores both against text
whose wording is already known, so you can check these numbers yourself:

| Reading | Tesseract | Windows' own reader |
|---|---|---|
| Code | **0.99**, indentation correct on every line | 0.46 – 0.84 |
| Ordinary writing | 1.00 | 1.00 |

For plain writing either reader is fine. For code the difference is large, because the
Windows reader is built for reading sentences and runs a dictionary over its guesses. On
code that works against you: `plt` becomes `pit`, `0` becomes `e`, and parts of a line are
**dropped without warning** — in testing, `i % 2 == 0` came back as nothing at all. That is
the worst kind of mistake, because the result still looks correct.

Even with Tesseract, two things to know:

- A zero on its own is sometimes read as `@` or `9`. Consolas, the default font in many
  editors, draws its zero with a slash through it. Numbers inside longer values, like
  `dpi=300`, are read correctly.
- Tabs come back as spaces. No reader can tell the two apart from a picture.

So check a snip before trusting it in something that matters.

## Turn it off

- **Until next restart:** Task Manager (Ctrl + Shift + Esc) > **pythonw.exe** > End task.
- **Remove from startup:** run
  ```
  powershell -ExecutionPolicy Bypass -File install-startup.ps1 -Uninstall
  ```

## Troubleshooting

- **Nothing happens on Ctrl+Alt+T:** another app may already use that shortcut. Change
  `HOTKEY_KEY` near the top of `text_snip.py`, then run the install command again.
- **Code comes out badly, with `plt` read as `pit`:** Tesseract isn't installed, so the
  Windows reader is being used. Run the install command in step 4 above, then restart
  text-snip with the command in step 5.
- **Other languages:** the Windows reader uses the languages installed in Windows
  Settings > Time & language > Language. Tesseract needs its own language files, and is
  installed with English only by default.
- **Errors** are written to `Documents\text-snips\text-snip-errors.log`.

## Running the tests

```
python tests/test_layout.py        # checks the shape of text survives, no screen needed
python tests/benchmark_readers.py  # scores both readers against known text
```

## License

MIT: free to use, change and share. See [LICENSE](LICENSE).

Made by [TheDanEffect](https://github.com/TheDanEffect).
