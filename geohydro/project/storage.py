"""GeoHydro Pro project file format (``.ghproj``), version 2.

A project file is a single SQLite 3 database. SQLite is used because it is
transactional, portable across Windows/Linux/macOS, readable from Python on
the planned web backend, and supports schema migrations. Full specification:
``docs/PROJECT_FORMAT.md``.

Safety rules implemented here:
  * Loading never modifies the file. Older format versions are migrated in
    memory; the upgraded version is written only when the user saves.
  * Saving writes to a temporary file in the same folder and atomically
    replaces the target; the previous file is kept as ``<name>.ghproj.bak``.
  * Saving refuses (raises) when the target belongs to a different project,
    or holds a newer revision of the same project, unless the caller passes
    an explicit ``overwrite=True`` / ``force=True`` after asking the user.
  * Every dataset table is stored with a SHA-256 checksum that is verified on
    load.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import sqlite3
import uuid as _uuid
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from geohydro import __version__
from geohydro.engine.data.dataset import PointDataset, SourceInfo, utc_now
from geohydro.engine.gridding.grid import Grid, GridGeometry
from geohydro.engine.mapping.model import MapDocument
from geohydro.engine.errors import (
    GriddingError,
    MapError,
    ProjectConflictError,
    ProjectFormatError,
    ProjectIntegrityError,
    ProjectOverwriteError,
)

from .model import HistoryEntry, Project

FORMAT_NAME = "GeoHydroPro.Project"
FORMAT_VERSION = 2
FILE_EXTENSION = ".ghproj"
DATA_ENCODING = "csv+gzip"
GRID_ENCODING = "npy-f8+gzip"

SCHEMA_V1 = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE project (
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    manifest TEXT NOT NULL            -- JSON: metadata, settings, outputs
);
CREATE TABLE datasets (
    id              TEXT PRIMARY KEY,
    position        INTEGER NOT NULL,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    crs             TEXT,
    xy_units        TEXT NOT NULL,
    z_units         TEXT NOT NULL,
    labels          TEXT NOT NULL,    -- JSON {x, y, z}: original column names
    created         TEXT NOT NULL,
    notes           TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL,    -- JSON SourceInfo
    import_settings TEXT NOT NULL,    -- JSON ImportSettings
    qc_report       TEXT NOT NULL,    -- JSON QCReport
    columns         TEXT NOT NULL,    -- JSON [{name, dtype}]
    n_rows          INTEGER NOT NULL,
    data_encoding   TEXT NOT NULL,
    data            BLOB NOT NULL,
    data_sha256     TEXT NOT NULL
);
CREATE TABLE history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    action      TEXT NOT NULL,
    details     TEXT NOT NULL,        -- JSON
    app_version TEXT NOT NULL
);
"""

# Added in format version 2 (Phase 2): grids and map documents.
SCHEMA_V2_ADDITIONS = """
CREATE TABLE grids (
    id            TEXT PRIMARY KEY,
    position      INTEGER NOT NULL,
    name          TEXT NOT NULL,
    crs           TEXT,
    xy_units      TEXT NOT NULL,
    z_units       TEXT NOT NULL,
    z_label       TEXT NOT NULL,
    geometry      TEXT NOT NULL,      -- JSON GridGeometry (node registered)
    metadata      TEXT NOT NULL,      -- JSON provenance: method, parameters, residuals ...
    notes         TEXT NOT NULL DEFAULT '',
    data_encoding TEXT NOT NULL,
    data          BLOB NOT NULL,      -- gzip(.npy float64, shape (ny, nx), NaN = blank)
    data_sha256   TEXT NOT NULL
);
CREATE TABLE maps (
    id        TEXT PRIMARY KEY,
    position  INTEGER NOT NULL,
    name      TEXT NOT NULL,
    document  TEXT NOT NULL           -- JSON MapDocument
);
"""
SCHEMA = SCHEMA_V1 + SCHEMA_V2_ADDITIONS


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_V2_ADDITIONS)


# from_version -> function(conn) upgrading the schema/data to from_version+1.
# Register migrations here whenever FORMAT_VERSION is increased.
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {1: _migrate_v1_to_v2}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=_json_default)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Not JSON serialisable: {type(o)}")


def _dtype_code(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_integer_dtype(s):
        return "int"
    if pd.api.types.is_float_dtype(s):
        return "float"
    return "string"


def encode_frame(df: pd.DataFrame) -> tuple[bytes, list[dict], str]:
    columns = [{"name": str(c), "dtype": _dtype_code(df[c])} for c in df.columns]
    buf = io.StringIO()
    df.to_csv(buf, index=False, float_format="%.17g", lineterminator="\n")
    raw = buf.getvalue().encode("utf-8")
    blob = gzip.compress(raw, compresslevel=6, mtime=0)
    return blob, columns, hashlib.sha256(blob).hexdigest()


def decode_frame(blob: bytes, columns: list[dict]) -> pd.DataFrame:
    raw = gzip.decompress(blob).decode("utf-8")
    df = pd.read_csv(io.StringIO(raw), dtype=str, keep_default_na=False)
    out = {}
    for col in columns:
        name, dt = col["name"], col["dtype"]
        s = df[name] if name in df.columns else pd.Series([""] * len(df))
        if dt == "float":
            out[name] = pd.to_numeric(s.replace("", np.nan), errors="raise").astype(float)
        elif dt == "int":
            out[name] = pd.to_numeric(s).astype("int64")
        elif dt == "bool":
            out[name] = s.map({"True": True, "False": False}).astype(bool)
        else:
            out[name] = s.astype(str)
    return pd.DataFrame(out, columns=[c["name"] for c in columns])


def encode_grid(z: np.ndarray) -> tuple[bytes, str]:
    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(z, dtype="<f8"), allow_pickle=False)
    blob = gzip.compress(buf.getvalue(), compresslevel=6, mtime=0)
    return blob, hashlib.sha256(blob).hexdigest()


def decode_grid(blob: bytes) -> np.ndarray:
    return np.load(io.BytesIO(gzip.decompress(blob)), allow_pickle=False)


def project_manifest(project: Project) -> dict:
    """Format-independent JSON description of a project (also used by web)."""
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "uuid": project.uuid,
        "name": project.name,
        "description": project.description,
        "author": project.author,
        "default_crs": project.default_crs,
        "units": project.units,
        "created": project.created,
        "modified": project.modified,
        "settings": project.settings,
        "outputs": project.outputs,
        "datasets": [
            {
                "id": d.id,
                "name": d.name,
                "kind": d.kind,
                "crs": d.crs,
                "xy_units": d.xy_units,
                "z_units": d.z_units,
                "n_points": d.n_points,
                "source": asdict(d.source),
            }
            for d in project.datasets.values()
        ],
        "grids": [
            {"id": g.id, "name": g.name, "crs": g.crs, "geometry": g.geometry.to_dict(),
             "method": (g.metadata or {}).get("method")}
            for g in project.grids.values()
        ],
        "maps": [{"id": m.id, "name": m.name} for m in project.maps.values()],
    }


# --------------------------------------------------------------------------
# header / validation
# --------------------------------------------------------------------------


def _read_meta(conn: sqlite3.Connection) -> dict:
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.DatabaseError as exc:
        raise ProjectFormatError(f"Not a GeoHydro Pro project file ({exc})") from exc
    meta = dict(rows)
    if meta.get("format_name") != FORMAT_NAME:
        raise ProjectFormatError("Not a GeoHydro Pro project file (format name missing)")
    try:
        meta["format_version"] = int(meta["format_version"])
        meta["revision"] = int(meta.get("revision", "0"))
    except (KeyError, ValueError) as exc:
        raise ProjectFormatError("Project file header is corrupt") from exc
    return meta


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("SELECT 1")
        return conn
    except sqlite3.DatabaseError as exc:
        raise ProjectFormatError(f"Cannot open project file: {exc}") from exc


def read_header(path: str | Path) -> dict:
    """Return the meta table of a project file without loading datasets."""
    path = Path(path)
    if not path.is_file():
        raise ProjectFormatError(f"Project file not found: {path}")
    conn = _connect_ro(path)
    try:
        return _read_meta(conn)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# save
# --------------------------------------------------------------------------


def _write_db(conn: sqlite3.Connection, project: Project, revision: int) -> None:
    conn.executescript(SCHEMA)
    now = utc_now()
    meta = {
        "format_name": FORMAT_NAME,
        "format_version": str(FORMAT_VERSION),
        "app_version": __version__,
        "project_uuid": project.uuid,
        "revision": str(revision),
        "created": project.created,
        "modified": project.modified,
        "saved_at": now,
        "data_encoding": DATA_ENCODING,
    }
    conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", list(meta.items()))
    conn.execute("INSERT INTO project(id, manifest) VALUES (1, ?)", (_json(project_manifest(project)),))
    for pos, ds in enumerate(project.datasets.values()):
        blob, cols, sha = encode_frame(ds.data)
        conn.execute(
            "INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ds.id, pos, ds.name, ds.kind, ds.crs, ds.xy_units, ds.z_units,
                _json({"x": ds.x_label, "y": ds.y_label, "z": ds.z_label}),
                ds.created, ds.notes, _json(asdict(ds.source)), _json(ds.import_settings),
                _json(ds.qc_report), _json(cols), ds.n_points, DATA_ENCODING, blob, sha,
            ),
        )
    for pos, g in enumerate(project.grids.values()):
        blob, sha = encode_grid(g.z)
        conn.execute(
            "INSERT INTO grids VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (g.id, pos, g.name, g.crs, g.xy_units, g.z_units, g.z_label,
             _json(g.geometry.to_dict()), _json(g.metadata), g.notes, GRID_ENCODING, blob, sha),
        )
    for pos, mp in enumerate(project.maps.values()):
        conn.execute("INSERT INTO maps VALUES (?,?,?,?)",
                     (mp.id, pos, mp.name, _json(mp.to_dict())))
    conn.executemany(
        "INSERT INTO history(timestamp, action, details, app_version) VALUES (?,?,?,?)",
        [(h.timestamp, h.action, _json(h.details), h.app_version) for h in project.history],
    )
    conn.commit()


def save_project(
    project: Project,
    path: str | Path | None = None,
    *,
    overwrite: bool = False,
    force: bool = False,
    keep_backup: bool = True,
) -> Path:
    """Save ``project`` to ``path`` (default: ``project.path``).

    Raises :class:`ProjectOverwriteError` if the target exists and is not
    this project (pass ``overwrite=True`` after user confirmation), and
    :class:`ProjectConflictError` if the target holds a newer revision of this
    project (pass ``force=True`` after user confirmation).
    """
    if path is None:
        if not project.path:
            raise ValueError("No file path given for an unsaved project")
        path = project.path
    path = Path(path)
    if path.suffix.lower() != FILE_EXTENSION:
        path = path.with_name(path.name + FILE_EXTENSION)
    path.parent.mkdir(parents=True, exist_ok=True)

    disk_rev = 0
    if path.exists():
        try:
            hdr = read_header(path)
        except ProjectFormatError:
            if not overwrite:
                raise ProjectOverwriteError(
                    f"{path.name} exists and is not a GeoHydro Pro project. Overwrite it?"
                )
            hdr = None
        if hdr is not None:
            if hdr["project_uuid"] != project.uuid:
                if not overwrite:
                    raise ProjectOverwriteError(
                        f"{path.name} contains a different project. Replace it?"
                    )
            else:
                disk_rev = hdr["revision"]
                if disk_rev > project.revision and not force:
                    raise ProjectConflictError(
                        f"{path.name} was saved elsewhere (revision {disk_rev}) after this copy was "
                        f"opened (revision {project.revision}). Saving would replace newer data."
                    )

    revision = max(project.revision, disk_rev) + 1
    project.modified = utc_now()
    tmp = path.with_name(f".{path.name}.{_uuid.uuid4().hex[:8]}.tmp")
    conn = sqlite3.connect(tmp)
    try:
        _write_db(conn, project, revision)
    except Exception:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    conn.close()
    with open(tmp, "rb+") as fh:
        os.fsync(fh.fileno())
    if path.exists() and keep_backup:
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)

    project.path = str(path)
    project.revision = revision
    project.dirty = False
    return path


# --------------------------------------------------------------------------
# load
# --------------------------------------------------------------------------


def _migrate(conn: sqlite3.Connection, from_version: int) -> list[int]:
    applied = []
    v = from_version
    while v < FORMAT_VERSION:
        fn = MIGRATIONS.get(v)
        if fn is None:
            raise ProjectFormatError(f"No migration available from format version {v}")
        fn(conn)
        v += 1
        conn.execute("UPDATE meta SET value=? WHERE key='format_version'", (str(v),))
        applied.append(v)
    conn.commit()
    return applied


def load_project(path: str | Path, *, verify: bool = True) -> Project:
    path = Path(path)
    if not path.is_file():
        raise ProjectFormatError(f"Project file not found: {path}")
    disk = _connect_ro(path)
    try:
        meta = _read_meta(disk)
        version = meta["format_version"]
        if version > FORMAT_VERSION:
            raise ProjectFormatError(
                f"{path.name} uses project format version {version}, created by GeoHydro Pro "
                f"{meta.get('app_version', '?')}. This version supports up to {FORMAT_VERSION}. "
                "Please update GeoHydro Pro."
            )
        if verify:
            res = disk.execute("PRAGMA integrity_check").fetchone()[0]
            if res != "ok":
                raise ProjectIntegrityError(f"SQLite integrity check failed: {res}")
        conn = sqlite3.connect(":memory:")
        disk.backup(conn)
    finally:
        disk.close()

    try:
        migrated = _migrate(conn, version) if version < FORMAT_VERSION else []
        (manifest_txt,) = conn.execute("SELECT manifest FROM project WHERE id=1").fetchone()
        m = json.loads(manifest_txt)
        proj = Project(
            name=m.get("name", path.stem),
            description=m.get("description", ""),
            author=m.get("author", ""),
            default_crs=m.get("default_crs"),
            units=m.get("units", "m"),
            uuid=meta["project_uuid"],
            created=meta.get("created", m.get("created")),
            modified=meta.get("modified", m.get("modified")),
            settings=m.get("settings", {}),
            outputs=m.get("outputs", []),
        )
        rows = conn.execute(
            "SELECT id, name, kind, crs, xy_units, z_units, labels, created, notes, source, "
            "import_settings, qc_report, columns, n_rows, data_encoding, data, data_sha256 "
            "FROM datasets ORDER BY position"
        ).fetchall()
        for (did, name, kind, crs, xyu, zu, labels, created, notes, source, isettings, qc,
             cols, n_rows, enc, blob, sha) in rows:
            if enc != DATA_ENCODING:
                raise ProjectFormatError(f"Dataset {name!r}: unsupported data encoding {enc!r}")
            if verify and hashlib.sha256(blob).hexdigest() != sha:
                raise ProjectIntegrityError(f"Dataset {name!r} failed checksum verification")
            df = decode_frame(blob, json.loads(cols))
            if len(df) != n_rows:
                raise ProjectIntegrityError(f"Dataset {name!r}: expected {n_rows} rows, found {len(df)}")
            lab = json.loads(labels)
            ds = PointDataset(
                name=name, data=df, source=SourceInfo(**json.loads(source)),
                import_settings=json.loads(isettings), qc_report=json.loads(qc), crs=crs,
                xy_units=xyu, z_units=zu, x_label=lab.get("x", "X"), y_label=lab.get("y", "Y"),
                z_label=lab.get("z", "Z"), id=did, kind=kind, created=created, notes=notes,
            )
            proj.datasets[did] = ds
        for (gid, name, crs, xyu, zu, zl, geom, md, notes, enc, blob, sha) in conn.execute(
            "SELECT id, name, crs, xy_units, z_units, z_label, geometry, metadata, notes, "
            "data_encoding, data, data_sha256 FROM grids ORDER BY position"
        ).fetchall():
            if enc != GRID_ENCODING:
                raise ProjectFormatError(f"Grid {name!r}: unsupported data encoding {enc!r}")
            if verify and hashlib.sha256(blob).hexdigest() != sha:
                raise ProjectIntegrityError(f"Grid {name!r} failed checksum verification")
            geometry = GridGeometry.from_dict(json.loads(geom))
            z = decode_grid(blob)
            if z.shape != geometry.shape:
                raise ProjectIntegrityError(f"Grid {name!r}: data shape does not match geometry")
            proj.grids[gid] = Grid(geometry, z, name=name, crs=crs, xy_units=xyu, z_units=zu,
                                   z_label=zl, metadata=json.loads(md), id=gid, notes=notes)
        for mid, name, doc in conn.execute(
            "SELECT id, name, document FROM maps ORDER BY position"
        ).fetchall():
            mp = MapDocument.from_dict(json.loads(doc))
            mp.id, mp.name = mid, name
            proj.maps[mid] = mp
        for ts, action, details, appv in conn.execute(
            "SELECT timestamp, action, details, app_version FROM history ORDER BY id"
        ):
            proj.history.append(HistoryEntry(ts, action, json.loads(details), appv))
    except (sqlite3.DatabaseError, KeyError, TypeError, ValueError, json.JSONDecodeError,
            GriddingError, MapError) as exc:
        raise ProjectFormatError(f"Project file is damaged or incomplete: {exc}") from exc
    finally:
        conn.close()

    proj.path = str(path)
    proj.revision = meta["revision"]
    proj.dirty = bool(migrated)
    if migrated:
        proj.history.append(HistoryEntry(utc_now(), "project.migrate",
                                         {"from_version": version, "to_version": FORMAT_VERSION}))
    return proj


def verify_project_file(path: str | Path) -> list[str]:
    """Full integrity verification; returns a list of human-readable results."""
    results = []
    hdr = read_header(path)
    results.append(f"Format {hdr['format_name']} v{hdr['format_version']}, revision {hdr['revision']}")
    proj = load_project(path, verify=True)
    results.append("SQLite integrity check: ok")
    for d in proj.datasets.values():
        results.append(f"Dataset '{d.name}': {d.n_points} rows, checksum ok")
    for g in proj.grids.values():
        results.append(f"Grid '{g.name}': {g.geometry.nx} x {g.geometry.ny} nodes, checksum ok")
    for m in proj.maps.values():
        missing = [i for i in m.referenced_ids() if proj.item(i) is None]
        results.append(f"Map '{m.name}': {len(m.layers)} layer(s)" +
                       (f", {len(missing)} missing data source(s)" if missing else ", sources ok"))
    return results
