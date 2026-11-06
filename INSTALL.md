# Installing XeroxPro on the shop computer (Windows 10/11, 64-bit)

You do **not** need Python or internet. Everything is inside the program folder.

## Option A — installer (easiest)

1. Run `XeroxPro-Setup-0.1.0.exe`.
2. Windows may say *"Windows protected your PC"* because the program is not code-signed. Click **More info → Run anyway**.
3. Accept the defaults. A desktop shortcut is offered.
4. Start **XeroxPro**. Go to the *First-time setup* section of `docs/USER_MANUAL.md`.

## Option B — plain folder (no installer)

1. Unzip `XeroxPro-windows.zip` anywhere (for example `C:\XeroxPro`).
2. Double-click `XeroxPro\XeroxPro.exe`. Right-click → *Send to → Desktop (create shortcut)* for a shortcut.

## Where your data lives (important)

| What | Where |
|---|---|
| Shop records (database) | `%LOCALAPPDATA%\XeroxPro\xeroxpro.db` (= `C:\Users\<name>\AppData\Local\XeroxPro`) |
| Error log | `%LOCALAPPDATA%\XeroxPro\logs\` |
| Backups | `Documents\XeroxPro Backups` (changeable) |

The program folder holds **no records**. Updating, reinstalling or even uninstalling does not touch your data.

## Updating to a newer version

Run the new installer (or replace the program folder with the new one). On first start the program upgrades the
database by itself and keeps a copy of the old one first (`pre-migration` folder). A newer database is never opened by
an older program (it refuses with a clear message).

## Moving to another computer

1. Old PC: *Backup & Restore → Copy to USB / another folder*.
2. New PC: install, start once, *Restore from a file…* and pick the backup file.

## Check that the installation works

Open Command Prompt in the program folder and run:

```
start /wait XeroxPro.exe --selftest C:\Temp\selftest.txt
type C:\Temp\selftest.txt
```

It must end with `SELFTEST PASSED`. It checks the bundled fonts, database, a Telugu receipt PDF, Excel/PDF reports,
backup and restore, printer listing and every screen — using a temporary folder, never your real data.
Then follow `docs/SHOP_PC_CHECKLIST.md` once on the real printers.

## Uninstalling

Windows *Settings → Apps → XeroxPro → Uninstall*. Your data stays in `%LOCALAPPDATA%\XeroxPro` (delete it only if you
really want to erase all records — make a backup first).

---

# For the person who builds the program

The Windows program must be built **on Windows** (PyInstaller cannot cross-compile). Two ways:

## 1. GitHub Actions (no Windows PC needed)

1. This folder should be its own repository (it currently sits inside a larger one). In the project folder:
   ```
   git init -b main
   git add .
   git commit -m "XeroxPro"
   ```
2. Create an empty **private** repository on github.com and push to it (`git remote add origin <url>`, `git push -u origin main`).
3. Open the repository → **Actions** → *Test and build Windows app* (it also runs on every push).
   It runs all tests on Ubuntu **and Windows**, builds the program on Windows, runs `--selftest` on the built program,
   and attaches `XeroxPro-windows.zip`, `XeroxPro-Setup-*.exe` and `selftest.txt` as **Artifacts**.
4. Download the artifact, copy it to the shop computer, follow *Installing* above.

## 2. On any Windows PC

1. Install Python 3.12 (64-bit) from python.org (tick *py launcher*).
2. Open Command Prompt in the project folder and run `packaging\build_windows.bat`
   (add `notests` to skip the test run). It builds `dist\XeroxPro\XeroxPro.exe` and runs the self-test.
3. Optional installer: install Inno Setup (free), open `packaging\installer.iss`, press Compile.

## Developing on Linux/macOS

```
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q      # whole test suite, no screen needed
.venv/bin/python main.py                           # run the app
```
