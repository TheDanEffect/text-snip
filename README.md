# text-snip

**Copy text from anything on your screen: YouTube videos, images, screenshots, PDFs, games.**

Press **Ctrl + Alt + T**, drag a box over the text, then press **Ctrl + V** anywhere to paste it.
Like the Windows Snipping Tool, but for text.

- The screen freezes and dims so you can grab text from a moving video
- Text goes straight to your clipboard
- Every grab is also saved to a notes file, with the date and time
- Uses the text reader built into Windows, so it works offline
- Runs quietly in the background (about 40 MB of RAM) and starts with Windows

## Requirements

- Windows 10 or 11
- [Python 3.10 or newer](https://www.python.org/downloads/). During install, tick **"Add Python to PATH"**.

## Install

1. Download this project: click the green **Code** button above, then **Download ZIP**, and unzip it
   somewhere permanent (for example `Documents\text-snip`).
2. Open the unzipped folder, click the address bar, type `powershell` and press Enter.
3. Install the two things it needs:
   ```
   pip install -r requirements.txt
   ```
4. Start it and make it start with Windows:
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

## Turn it off

- **Until next restart:** Task Manager (Ctrl + Shift + Esc) > **pythonw.exe** > End task.
- **Remove from startup:** run
  ```
  powershell -ExecutionPolicy Bypass -File install-startup.ps1 -Uninstall
  ```

## Troubleshooting

- **Nothing happens on Ctrl+Alt+T:** another app may already use that shortcut. Change
  `HOTKEY_KEY` near the top of `text_snip.py`, then run the install command again.
- **Other languages:** it reads the languages installed in Windows Settings > Time & language > Language.
- **Errors** are written to `Documents\text-snips\text-snip-errors.log`.

## License

MIT: free to use, change and share. See [LICENSE](LICENSE).

Made by [TheDanEffect](https://github.com/TheDanEffect).
