# GeoHydro Pro v0.3.0 — Windows Installation Guide

For Windows 10 and Windows 11 (64-bit). No Python, GitHub account, programming tools
or separate downloads are needed to install or run the program.

| | |
|---|---|
| Version | 0.3.0 (development pre-release, 2026-11-20) |
| Built from | tag `v0.3.0`, commit `aa2284f`, by the *windows-package* GitHub Actions workflow (run 44767531360) |
| Tested | automated: frozen self-test, silent install, self-test of the installed copy, silent uninstall, all passed on Windows Server 2022. Not yet tested interactively on desktop Windows 10/11; your installation is that test. |

## 1. What is in the package

Folder `GeoHydro-Pro_v0.3.0_Windows_Installation_Package`:

| File | What it is | Do you need it? |
|---|---|---|
| `GeoHydroPro-0.3.0-Setup.exe` | **The installer. This is the file you run.** | Yes |
| `GeoHydroPro-0.3.0-win64.zip` | Portable version: unzip and run, no installation | Only if you cannot or do not want to install (§5) |
| `GeoHydro-Pro_v0.3.0_Installation_Guide.pdf` | This guide | |
| `GeoHydro-Pro_v0.3.0_Quick_Start_Guide.pdf` | First steps after installation | Recommended |
| `GeoHydroPro-0.3.0-selftest.txt` | Self-test report of exactly this build, made on the build machine | For reference |
| `uat_plane_utm39n.xyz` | Sample XYZ dataset (328 points, exact plane, UTM zone 39N) | Used in the Quick Start |
| `RELEASE_NOTES_v0.3.0.md` | What is new and the known limitations | |
| `SHA256SUMS.txt` | Checksums to confirm the files downloaded intact (§2.2) | Optional |
| `README.txt` | Short version of steps 2 to 4 | |

**Everything the program needs is inside the installer** (and inside the portable
zip): the Python 3.12 runtime, Qt 6.10 user interface, NumPy, SciPy, pandas,
Matplotlib, GDAL 3.12, PROJ 9.8, GEOS, and the Microsoft Visual C++ runtime DLLs.
Nothing else has to be installed. The program does not need an internet connection.

## 2. Download

### 2.1 Which file to download

If you received the whole package as one archive,
`GeoHydro-Pro_v0.3.0_Windows_Installation_Package.zip`, download it, right-click it
and choose **Extract All…**. Otherwise download at least
`GeoHydroPro-0.3.0-Setup.exe`.

The GitHub repository is private: release links work only when you are signed in to
GitHub with an account that has access to `eabushandi/GeoHydro-Pro`.

### 2.2 Check the download (optional, recommended)

Open **PowerShell** (Start ▸ type *PowerShell*), go to the download folder and run:

```
Get-FileHash .\GeoHydroPro-0.3.0-Setup.exe -Algorithm SHA256
```

The hash must equal the value in `SHA256SUMS.txt`:

| File | SHA-256 |
|---|---|
| `GeoHydroPro-0.3.0-Setup.exe` | `66d557415d3cffa22c3a60a707cd45981103f2447442865ea3deb527fda27987` |
| `GeoHydroPro-0.3.0-win64.zip` | `bee33491c4434d0b8f86bb395b56a960fa39cafcdfac33e3b13d4587d8d77e75` |
| `GeoHydroPro-0.3.0-selftest.txt` | `7f6c749f54955ebc71f92c41336b785189727c95a446548fa271cc0298bc534c` |

A different hash means the file is damaged or not the original. Download it again.

## 3. Install

**Requirements:** Windows 10 or 11, 64-bit; about 500 MB free disk space; no
administrator rights needed.

1. Double-click **`GeoHydroPro-0.3.0-Setup.exe`**.
2. Windows may show **"Windows protected your PC"** (SmartScreen). This appears
   because the installer is new and not yet code-signed. Click **More info**, check
   that the app is `GeoHydroPro-0.3.0-Setup.exe`, then click **Run anyway**.
3. If asked, choose **Install for me only** (recommended, no administrator rights).
   *Install for all users* needs administrator rights.
4. Accept the installation folder. The default for *Install for me only* is
   `C:\Users\<you>\AppData\Local\Programs\GeoHydro Pro`.
5. On **Select Additional Tasks**:
   * leave **Create a desktop shortcut** ticked (this creates the desktop icon);
   * leave **Open .ghproj project files with GeoHydro Pro** ticked.
6. Click **Install**. Copying may take a minute or two.
7. On the last page, leave **Start GeoHydro Pro with the sample project** ticked and
   click **Finish**.

### Desktop shortcut

* The installer creates it when *Create a desktop shortcut* is ticked (step 5).
* If you skipped it: open the Start menu, type **GeoHydro Pro**, right-click the
  result ▸ **Open file location**, then right-click **GeoHydro Pro** ▸ **Send to** ▸
  **Desktop (create shortcut)**. Or re-run the installer and tick the box.
* Portable version: right-click `GeoHydroPro.exe` ▸ **Send to** ▸ **Desktop (create
  shortcut)**.

### Start menu entries

| Entry | Starts |
|---|---|
| **GeoHydro Pro** | the program |
| **GeoHydro Pro (open sample project)** | the program with point data, grids and maps |
| **GeoHydro Pro (open GIS demo project)** | terrain, drainage, land use and flood-density maps |
| **GeoHydro Pro installation self-test** | a check of the installation (§4) |

## 4. Check the installation

Start **GeoHydro Pro installation self-test** from the Start menu. Nothing appears on
screen for up to a minute; then the file **`GeoHydroPro-selftest.txt`** is in your
**Documents** folder. Open it. The last line must be:

```
RESULT: all checks passed
```

It should list eight `PASS` lines (scientific libraries, PROJ database, sample project,
gridding and map export, raster I/O, vector I/O, GIS demo project, main window), like
the build machine's report included in the package. The second line will name your
Windows version instead of *Windows-2022Server*.

If a line says `FAIL`, see §7.

## 5. Portable version (no installation)

1. Right-click `GeoHydroPro-0.3.0-win64.zip` ▸ **Extract All…** to a folder you can
   write to, for example `Documents\GeoHydroPro`. Do not extract into
   `C:\Program Files`.
2. Open the extracted `GeoHydroPro` folder and double-click **`GeoHydroPro.exe`**.
   Keep the `_internal` folder next to it; the program needs it.
3. Self-test from a command prompt in that folder:
   `GeoHydroPro.exe --selftest --report "%USERPROFILE%\Documents\GeoHydroPro-selftest.txt"`

The portable version has no Start menu entries, no file association and no
uninstaller; delete the folder to remove it.

## 6. First-time setup

1. Start **GeoHydro Pro** (desktop icon or Start menu). The start page appears with
   the menu bar, ribbon, Project Explorer (left), Properties (right) and Output
   Console (bottom).
2. **Help ▸ About GeoHydro Pro** must show version **0.3.0**.
3. **Settings ▸ Default Length Unit**: metre is the default; change it if you work
   in feet.
4. **File ▸ New Project**. Click the project name in the Project Explorer and, in
   the Properties panel, set **Coordinate system ▸ Default CRS** to the system of
   your data (for the sample dataset: `EPSG:32639`, WGS 84 / UTM zone 39N).
5. **File ▸ Save Project As…** to choose where the project file (`.ghproj`) is kept.

Then follow the **Quick Start Guide**.

Settings (window layout, recent files) are stored in the registry under
`HKEY_CURRENT_USER\Software\GeoHydro Pro\GeoHydro Pro`.

## 7. Troubleshooting

| Problem | Solution |
|---|---|
| "Windows protected your PC" | Normal for an unsigned new program. **More info ▸ Run anyway** (§3 step 2). |
| Setup says the program cannot be installed on this version or architecture of Windows | A 64-bit (x64) Windows 10 or 11 is required; the installer refuses 32-bit Windows and versions older than 10. Windows on ARM (x64 emulation) is not tested. |
| The installer asks for an administrator password | You chose *Install for all users*. Go back and choose *Install for me only*. |
| Antivirus blocks or quarantines `GeoHydroPro.exe` or files in `_internal` | Some antivirus programs flag new, unsigned programs. Compare the installer's SHA-256 (§2.2), restore the files, and add an exclusion for the installation folder. Please report the antivirus product. |
| Nothing happens when starting, or the window flashes and closes | Run the self-test (§4). A `FAIL` line names the missing part. Uninstall, reinstall, and run the self-test again. |
| Self-test fails at "PROJ database" | `proj.db` was removed (often by a security tool). Reinstall. |
| Self-test fails at "Raster I/O" or "Vector I/O" | GDAL files were removed. Reinstall. |
| Black, blank or garbled window | Update the graphics driver. Workaround: Start ▸ type *environment variables* ▸ *Edit environment variables for your account* ▸ **New**: name `QT_OPENGL`, value `software` ▸ OK, then start again. |
| Text or icons too small or too large | Settings ▸ System ▸ Display ▸ Scale; restart GeoHydro Pro afterwards. |
| Double-clicking a `.ghproj` file does not open GeoHydro Pro | Re-run the installer and tick *Open .ghproj project files with GeoHydro Pro*. |
| "This project was created with a newer version" | The file was saved by a newer GeoHydro Pro. |
| Not enough disk space | About 500 MB is needed in the installation folder. |
| Installation folder already exists or files are in use | Close GeoHydro Pro (check the taskbar), then run the installer again; it updates the existing installation. |

When reporting a problem, include the self-test report and the console log
(**Save log…** in the Output Console).

## 8. Uninstall

**Settings ▸ Apps ▸ Installed apps ▸ GeoHydro Pro ▸ Uninstall** (Windows 11), or
**Control Panel ▸ Programs and Features** (Windows 10). Your projects and exported
files are not touched.

## 9. Limitations of this version

GeoHydro Pro 0.3.0 is a development pre-release, not certified for engineering use.
It has not yet been tested interactively on desktop Windows 10/11, and it is not
code-signed. Features labelled *planned* in the menus are disabled. Known issues
and the full feature list are in `RELEASE_NOTES_v0.3.0.md` and the UAT guide.
