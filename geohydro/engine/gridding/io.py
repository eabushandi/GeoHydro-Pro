"""Grid file reading and writing.

Supported formats
-----------------
* **Surfer 6 text grid** (``DSAA``, ``.grd``) - read and write.
* **Surfer 6 binary grid** (``DSBB``, ``.grd``) - read and write (float32 values).
* **Surfer 7 binary grid** (``DSRB``, ``.grd``) - read and write (float64 values).
* **ESRI ASCII grid** (``.asc``) - read and write. Requires square cells.
* **XYZ node table** (``.csv`` / ``.xyz``) - write only (X, Y, Z per node).

The Surfer layouts follow Golden Software's published grid-format
descriptions. They are covered by round-trip tests in this repository; they
have *not* yet been checked against files written by Surfer itself.

ESRI ASCII grids are cell-registered. A cell centre is mapped to a grid node,
so ``xllcorner + cellsize/2`` becomes ``x_min``. Files are written with
``xllcenter``/``yllcenter`` so that no half-cell shift is introduced.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np

from ..errors import GridFileError
from .grid import Grid, GridGeometry

SURFER_BLANK = 1.70141e38
ESRI_NODATA = -9999.0

GRID_FORMATS = {
    "surfer_ascii": ("Surfer 6 text grid (*.grd)", ".grd"),
    "surfer6_binary": ("Surfer 6 binary grid (*.grd)", ".grd"),
    "surfer7_binary": ("Surfer 7 binary grid (*.grd)", ".grd"),
    "esri_ascii": ("ESRI ASCII grid (*.asc)", ".asc"),
    "xyz": ("XYZ node table (*.csv)", ".csv"),
}


# ---------------------------------------------------------------- reading
def read_grid(path, name: str | None = None) -> Grid:
    path = Path(path)
    if not path.exists():
        raise GridFileError(f"Grid file not found: {path}")
    with open(path, "rb") as fh:
        head = fh.read(4)
    try:
        if head == b"DSAA":
            g = _read_dsaa(path)
        elif head == b"DSBB":
            g = _read_dsbb(path)
        elif head == b"DSRB":
            g = _read_dsrb(path)
        elif path.suffix.lower() in (".asc", ".txt") or head.lower().startswith(b"ncol"):
            g = _read_esri(path)
        else:
            raise GridFileError(
                f"{path.name}: unrecognised grid format (expected Surfer DSAA/DSBB/DSRB "
                "or ESRI ASCII)."
            )
    except GridFileError:
        raise
    except (ValueError, struct.error, IndexError) as exc:
        raise GridFileError(f"{path.name}: grid file is damaged or truncated ({exc}).") from exc
    g.name = name or path.stem
    g.metadata.setdefault("source", {})["path"] = str(path.resolve())
    return g


def _read_dsaa(path: Path) -> Grid:
    tokens = path.read_text(encoding="ascii", errors="strict").split()
    if tokens[0] != "DSAA":
        raise GridFileError("Not a Surfer text grid.")
    nx, ny = int(tokens[1]), int(tokens[2])
    x0, x1, y0, y1 = (float(t) for t in tokens[3:7])
    vals = np.array(tokens[9:9 + nx * ny], dtype=float)
    if vals.size != nx * ny:
        raise GridFileError(f"Expected {nx * ny} values, found {vals.size}.")
    z = vals.reshape(ny, nx)
    z[z >= SURFER_BLANK * 0.999999] = np.nan
    return Grid(GridGeometry(x0, x1, y0, y1, nx, ny), z,
                metadata={"source": {"format": "surfer_ascii"}})


def _read_dsbb(path: Path) -> Grid:
    data = path.read_bytes()
    nx, ny = struct.unpack_from("<hh", data, 4)
    x0, x1, y0, y1, _zlo, _zhi = struct.unpack_from("<6d", data, 8)
    z = np.frombuffer(data, dtype="<f4", count=nx * ny, offset=56).astype(float).reshape(ny, nx)
    z[z >= SURFER_BLANK * 0.999] = np.nan
    return Grid(GridGeometry(x0, x1, y0, y1, nx, ny), z,
                metadata={"source": {"format": "surfer6_binary"}})


def _read_dsrb(path: Path) -> Grid:
    data = path.read_bytes()
    pos = 0
    geom = None
    z = None
    blank = SURFER_BLANK
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4]
        size = struct.unpack_from("<i", data, pos + 4)[0]
        body = pos + 8
        if tag == b"GRID":
            ny, nx = struct.unpack_from("<ii", data, body)
            xll, yll, xs, ys, _zmin, _zmax, rot, blank = struct.unpack_from("<8d", data, body + 8)
            if rot != 0:
                raise GridFileError("Rotated Surfer 7 grids are not supported.")
            geom = GridGeometry(xll, xll + (nx - 1) * xs, yll, yll + (ny - 1) * ys, nx, ny)
        elif tag == b"DATA":
            if geom is None:
                raise GridFileError("DATA section before GRID section.")
            z = np.frombuffer(data, dtype="<f8", count=geom.n_nodes, offset=body).copy()
            z = z.reshape(geom.ny, geom.nx)
        pos = body + size
    if geom is None or z is None:
        raise GridFileError("Surfer 7 grid without GRID/DATA sections.")
    z[z >= blank] = np.nan
    return Grid(geom, z, metadata={"source": {"format": "surfer7_binary"}})


def _read_esri(path: Path) -> Grid:
    hdr = {}
    with open(path, encoding="ascii") as fh:
        lines = fh.read().splitlines()
    i = 0
    while i < len(lines):
        parts = lines[i].split()
        if len(parts) == 2 and parts[0][0].isalpha():
            hdr[parts[0].lower()] = float(parts[1])
            i += 1
        else:
            break
    for key in ("ncols", "nrows", "cellsize"):
        if key not in hdr:
            raise GridFileError(f"ESRI ASCII grid header is missing '{key}'.")
    nx, ny, cs = int(hdr["ncols"]), int(hdr["nrows"]), hdr["cellsize"]
    if "xllcenter" in hdr:
        x0 = hdr["xllcenter"]
    elif "xllcorner" in hdr:
        x0 = hdr["xllcorner"] + cs / 2
    else:
        raise GridFileError("ESRI ASCII grid header is missing xllcorner/xllcenter.")
    if "yllcenter" in hdr:
        y0 = hdr["yllcenter"]
    elif "yllcorner" in hdr:
        y0 = hdr["yllcorner"] + cs / 2
    else:
        raise GridFileError("ESRI ASCII grid header is missing yllcorner/yllcenter.")
    vals = np.array(" ".join(lines[i:]).split(), dtype=float)
    if vals.size != nx * ny:
        raise GridFileError(f"Expected {nx * ny} values, found {vals.size}.")
    z = vals.reshape(ny, nx)[::-1].copy()  # file rows run north to south
    nodata = hdr.get("nodata_value")
    if nodata is not None:
        z[z == nodata] = np.nan
    geom = GridGeometry(x0, x0 + (nx - 1) * cs, y0, y0 + (ny - 1) * cs, nx, ny)
    return Grid(geom, z, metadata={"source": {"format": "esri_ascii"}})


# ---------------------------------------------------------------- writing
def write_grid(grid: Grid, path, fmt: str | None = None, overwrite: bool = False) -> Path:
    path = Path(path)
    fmt = fmt or _guess_format(path)
    if fmt not in GRID_FORMATS:
        raise GridFileError(f"Unknown grid format '{fmt}'.")
    if path.exists() and not overwrite:
        raise GridFileError(f"{path} already exists.")
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        {
            "surfer_ascii": _write_dsaa,
            "surfer6_binary": _write_dsbb,
            "surfer7_binary": _write_dsrb,
            "esri_ascii": _write_esri,
            "xyz": _write_xyz,
        }[fmt](grid, tmp)
        os.replace(tmp, path)
    except OSError as exc:
        raise GridFileError(f"Could not write {path}: {exc}") from exc
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def _guess_format(path: Path) -> str:
    ext = path.suffix.lower()
    return {".asc": "esri_ascii", ".csv": "xyz", ".xyz": "xyz"}.get(ext, "surfer_ascii")


def _zrange(grid: Grid) -> tuple[float, float]:
    v = grid.z[np.isfinite(grid.z)]
    return (float(v.min()), float(v.max())) if v.size else (0.0, 0.0)


def _write_dsaa(grid: Grid, path: Path) -> None:
    g = grid.geometry
    zlo, zhi = _zrange(grid)
    z = np.where(np.isfinite(grid.z), grid.z, SURFER_BLANK)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("DSAA\n")
        fh.write(f"{g.nx} {g.ny}\n")
        fh.write(f"{g.x_min!r} {g.x_max!r}\n{g.y_min!r} {g.y_max!r}\n{zlo!r} {zhi!r}\n")
        for row in z:
            # 10 values per line, as Surfer does; repr keeps full precision.
            for k in range(0, row.size, 10):
                fh.write(" ".join(repr(float(v)) for v in row[k:k + 10]) + "\n")
            fh.write("\n")


def _write_dsbb(grid: Grid, path: Path) -> None:
    g = grid.geometry
    if g.nx > 32767 or g.ny > 32767:
        raise GridFileError("Surfer 6 binary grids are limited to 32767 nodes per side.")
    zlo, zhi = _zrange(grid)
    z = np.where(np.isfinite(grid.z), grid.z, SURFER_BLANK).astype("<f4")
    with open(path, "wb") as fh:
        fh.write(b"DSBB")
        fh.write(struct.pack("<hh", g.nx, g.ny))
        fh.write(struct.pack("<6d", g.x_min, g.x_max, g.y_min, g.y_max, zlo, zhi))
        fh.write(z.tobytes())


def _write_dsrb(grid: Grid, path: Path) -> None:
    g = grid.geometry
    zlo, zhi = _zrange(grid)
    z = np.where(np.isfinite(grid.z), grid.z, SURFER_BLANK).astype("<f8")
    with open(path, "wb") as fh:
        fh.write(b"DSRB" + struct.pack("<ii", 4, 2))
        fh.write(b"GRID" + struct.pack("<i", 72))
        fh.write(struct.pack("<ii", g.ny, g.nx))
        fh.write(struct.pack("<8d", g.x_min, g.y_min, g.dx, g.dy, zlo, zhi, 0.0, SURFER_BLANK))
        fh.write(b"DATA" + struct.pack("<i", z.nbytes))
        fh.write(z.tobytes())


def _write_esri(grid: Grid, path: Path) -> None:
    g = grid.geometry
    if abs(g.dx - g.dy) > 1e-9 * max(abs(g.dx), 1.0):
        raise GridFileError(
            f"ESRI ASCII grids need square cells; this grid has dx={g.dx:g}, dy={g.dy:g}."
        )
    finite = grid.z[np.isfinite(grid.z)]
    nodata = ESRI_NODATA
    while finite.size and np.any(finite == nodata):
        nodata *= 10
    z = np.where(np.isfinite(grid.z), grid.z, nodata)[::-1]
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write(f"ncols {g.nx}\nnrows {g.ny}\n")
        fh.write(f"xllcenter {g.x_min!r}\nyllcenter {g.y_min!r}\n")
        fh.write(f"cellsize {g.dx!r}\nNODATA_value {nodata!r}\n")
        for row in z:
            fh.write(" ".join(repr(float(v)) for v in row) + "\n")


def _write_xyz(grid: Grid, path: Path) -> None:
    xx, yy = grid.geometry.mesh()
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"X,Y,{grid.z_label or 'Z'}\n")
        for x, y, z in zip(xx.ravel(), yy.ravel(), grid.z.ravel()):
            fh.write(f"{x!r},{y!r},{'' if not np.isfinite(z) else repr(float(z))}\n")
