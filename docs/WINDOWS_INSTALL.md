# Installing GeoHydro Pro on Windows

This guide covers the standalone Windows build: an installer and a portable
zip. Neither needs Python, GDAL or any other separate installation. To run
from source instead, see `docs/INSTALL.md`.

> **Compatibility status.** Every build is tested automatically on GitHub
> Actions Windows Server 2022 images. CI checks the frozen self-test, a silent
> install, a self-test of the installed copy, and a silent uninstall. Windows
> Server shares its code base with Windows 10/11, but **the build has not yet
> been checked interactively on desktop Windows 10 or Windows 11**. Please
> report anything that behaves differently there.

## 1. Requirements

* Windows 10 or Windows 11, 64-bit (x64). The installer refuses older systems.
* About 500 MB of disk space. The application folder holds Python, Qt, GDAL
  and PROJ and measured 474 MB for version 0.3.0 (the installer itself is
  132 MB). Every build log prints the size ("Application folder size").
* No administrator rights for a per-user installation (the default).

The memory and display recommendations in `docs/INSTALL.md` are provisional.
They have not been measured.

## 2. Download

Each version is published as a GitHub release with three files:

| File | What it is |
|---|---|
| `GeoHydroPro-<version>-Setup.exe` | installer (recommended) |
| `GeoHydroPro-<version>-win64.zip` | portable folder; unzip and run `GeoHydroPro.exe` |
| `GeoHydroPro-<version>-selftest.txt` | self-test report of exactly this build, produced by CI |

Builds from the latest `main` branch are also available as the
`GeoHydroPro-windows` artifact of the most recent *windows-package* workflow
run (kept for 30 days).

The files are **not code-signed yet**. Code signing needs a paid certificate
and is planned for the production release.

## 3. Install

1. Run `GeoHydroPro-<version>-Setup.exe`.
2. **Windows SmartScreen** may show "Windows protected your PC" because the
   file is new and unsigned. Click **More info**, check that the app name is
   `GeoHydroPro-<version>-Setup.exe`, and click **Run anyway**. Only do this
   for files downloaded from the project's own GitHub release page.
3. Choose **Install for me only** (no administrator rights) or **Install for
   all users** (needs administrator rights).
4. Optional tasks:
   * a desktop shortcut
   * opening `.ghproj` files with GeoHydro Pro (file association)
5. At the end, you can start GeoHydro Pro with the sample project.

Start menu entries:

* **GeoHydro Pro**
* **GeoHydro Pro (open sample project)**: point data, grids and maps.
* **GeoHydro Pro (open GIS demo project)**: terrain, drainage, land use and
  flood-report density (synthetic data).
* **GeoHydro Pro installation self-test**: writes `GeoHydroPro-selftest.txt`
  to your Documents folder.

Silent installation (IT departments):

```
GeoHydroPro-<version>-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /DIR="C:\Apps\GeoHydroPro"
```

Use `/ALLUSERS` instead of `/CURRENTUSER` for a machine-wide installation
(administrator rights needed).

### Portable zip

Unzip the whole folder anywhere you can write to, for example a USB drive or
`Documents\GeoHydroPro`. Then run `GeoHydroPro.exe`.

* Keep the `_internal` folder next to the exe. The program needs it.
* Do not unzip into `C:\Program Files` without administrator rights.

## 4. Check the installation

Run the Start menu entry **GeoHydro Pro installation self-test**, or from a
command prompt:

```
"%LOCALAPPDATA%\Programs\GeoHydro Pro\GeoHydroPro.exe" --selftest --report "%USERPROFILE%\Documents\GeoHydroPro-selftest.txt"
```

The path above is the default per-user location. The self-test runs without
user interaction and checks that:

* the scientific libraries load
* PROJ finds its database (a UTM coordinate is computed and compared)
* the sample project opens and its checksums verify
* a grid can be interpolated and exported as PNG, PDF and SVG
* GeoTIFF and GeoPackage files can be written and read back through GDAL
* the GIS demo project opens and its map exports
* the main window can be created

The report ends with `RESULT: all checks passed`. The program's exit code is 0
on success.

## 5. Uninstall

Use **Settings ▸ Apps ▸ Installed apps ▸ GeoHydro Pro ▸ Uninstall** (Windows 11),
or **Control Panel ▸ Programs and Features** (Windows 10).

* Your projects and exported files are not touched.
* Settings (window layout, recent files) stay in the registry under
  `HKEY_CURRENT_USER\Software\GeoHydro Pro\GeoHydro Pro`. Delete that key to
  remove them.

For the portable zip, delete the folder.

## 6. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| "Windows protected your PC" | The build is unsigned. See §3 step 2. |
| Antivirus quarantines `GeoHydroPro.exe` or files in `_internal` | Some antivirus products flag new PyInstaller-built programs. Restore the files and add an exclusion for the installation folder, or report the false positive to the antivirus vendor. Check the file against the release's self-test report first. |
| Nothing happens when starting, or the window flashes and closes | Run the self-test (§4) and read the report. A `FAIL` line names the missing component. Reinstall if a library or data file is missing. |
| Self-test fails at "PROJ database" | The `_internal\pyproj\proj_dir\share\proj` folder is missing or blocked. Reinstall, and make sure no security tool removed `proj.db`. |
| Self-test fails at "Raster I/O" or "Vector I/O" | The GDAL data or libraries were removed. Reinstall. |
| Blank or black window, or the window is drawn incorrectly | Usually a graphics-driver problem. Update the graphics driver. As a workaround, set the environment variable `QT_OPENGL=software` before starting. |
| Text or icons too small or too large | Windows display scaling is respected. Set scaling in **Settings ▸ System ▸ Display**, then restart GeoHydro Pro. |
| Double-clicking a `.ghproj` file does not open GeoHydro Pro | Re-run the installer and tick **Open .ghproj project files with GeoHydro Pro**. |
| "This project was created with a newer version" | The file was saved by a newer GeoHydro Pro. Install the newer version; older versions never overwrite newer files. |
| A project from v0.1 or v0.2 opens as modified | It was upgraded to format v3 in memory. The file on disk is unchanged until you save. A `.bak` copy of the old file is kept when you save. |
| Import of a shapefile shows "no coordinate reference system" | The `.prj` file is missing. Copy it next to the `.shp`, or assign the CRS in the Properties panel. Assigning does not move coordinates. |
| A raster opens as an image when you wanted values | In the import dialog choose **Import as: Grid**. Images hold colours only and cannot be analysed. |
| Point density says it needs projected coordinates | The points are in longitude/latitude. Reproject them first (Data ▸ Vector Processing ▸ Reproject), or import them with a projected CRS. |

When reporting a problem, please attach the self-test report and the Output
Console log (**Save log…** in the console panel).

## 7. Building the package yourself

From a clone of the repository, in a 64-bit Python 3.12 environment on
Windows:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

This installs the build requirements, then runs PyInstaller in one-folder
mode and the frozen self-test. It then writes the portable zip and, if Inno
Setup 6 is installed, the installer, all to `dist\`. The same script runs in
the *windows-package* GitHub workflow.
