"""Readers for tabular point data: CSV, TXT, DAT, XYZ and XLSX.

All readers return a :class:`RawTable` whose cells are *strings exactly as
they appear in the source* (for XLSX: the cell value rendered with full
precision). Numeric conversion is deliberately a separate, audited step
(:mod:`geohydro.engine.data.qc`) so every rejected value can be explained.

Source files are opened read-only and are never modified.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd

from ..errors import DataReadError
from .formats import detect_format, planned_format_for
from .parsing import looks_numeric

ENCODING_CANDIDATES = ("utf-8-sig", "cp1252", "latin-1")
DELIMITER_NAMES = {
    ",": "Comma",
    ";": "Semicolon",
    "\t": "Tab",
    "|": "Pipe",
    "whitespace": "Whitespace",
}
# Priority order matters: semicolon is tested before comma so that
# "1,5;2,3" (decimal comma) is not split on the comma.
_DELIM_PRIORITY = ("\t", ";", ",", "|", "whitespace")
_WS = re.compile(r"\s+")


@dataclass
class ReadOptions:
    format: str | None = None  # csv | xlsx | xyz | txt | dat ; None = from extension
    delimiter: str | None = None  # None = auto; one of DELIMITER_NAMES keys
    header: str = "auto"  # auto | yes | no
    skip_rows: int = 0  # physical lines (or sheet rows) skipped before parsing
    comment: str | None = "#"
    encoding: str | None = None  # None = auto
    decimal: str | None = None  # "." | "," | None = auto
    sheet: str | None = None  # XLSX sheet name; None = first sheet
    max_rows: int | None = None  # limit data rows (for previews)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ReadOptions":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class RawTable:
    frame: pd.DataFrame  # all cells as str
    options: ReadOptions  # options as resolved (auto values filled in)
    source_format: str
    total_data_rows: int  # data rows in the file (before max_rows truncation)
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)

    @property
    def columns(self) -> list[str]:
        return [str(c) for c in self.frame.columns]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def read_table(path: str | Path, options: ReadOptions | None = None) -> RawTable:
    path = Path(path)
    opts = ReadOptions(**(options.to_dict() if options else {}))
    if not path.exists():
        raise DataReadError(f"File not found: {path}")
    if not path.is_file():
        raise DataReadError(f"Not a file: {path}")

    fmt = opts.format or detect_format(path)
    if fmt is None:
        planned = planned_format_for(path)
        if planned:
            code, desc, phase = planned
            raise DataReadError(
                f"{desc} files are planned for Phase {phase} and are not supported yet: {path.name}"
            )
        # Unknown extension: try as delimited text
        fmt = "txt"
    opts.format = fmt

    if fmt == "xlsx":
        return _read_xlsx(path, opts)
    return _read_text(path, opts)


def list_sheets(path: str | Path) -> list[str]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types
        raise DataReadError(f"Cannot open workbook {Path(path).name}: {exc}") from exc
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


# --------------------------------------------------------------------------
# Text formats
# --------------------------------------------------------------------------


def _decode(data: bytes, encoding: str | None) -> tuple[str, str]:
    if encoding:
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError) as exc:
            raise DataReadError(f"File is not valid {encoding}: {exc}") from exc
    for enc in ENCODING_CANDIDATES:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise DataReadError("Unable to decode file")  # pragma: no cover (latin-1 never fails)


def _split(line: str, delim: str) -> list[str]:
    if delim == "whitespace":
        return _WS.split(line.strip())
    return next(csv.reader([line], delimiter=delim, quotechar='"', skipinitialspace=True))


def _detect_delimiter(lines: list[str], fmt: str) -> str:
    sample = lines[:200]
    if not sample:
        return "whitespace" if fmt == "xyz" else ","
    best = None
    for delim in _DELIM_PRIORITY:
        if delim != "whitespace" and not any(delim in ln for ln in sample):
            continue
        counts = [len(_split(ln, delim)) for ln in sample]
        mode, freq = Counter(counts).most_common(1)[0]
        consistency = freq / len(counts)
        if mode >= 2 and consistency >= 0.9:
            return delim
        score = (consistency if mode >= 2 else 0.0, mode)
        if best is None or score > best[0]:
            best = (score, delim)
    if fmt == "xyz":
        return "whitespace"
    return best[1] if best and best[0][0] > 0 else ","


def _detect_decimal(rows: list[list[str]], delim: str) -> str:
    if delim == ",":
        return "."
    comma_num = re.compile(r"^[+-]?\d+,\d+([eE][+-]?\d+)?$")
    dot_num = re.compile(r"^[+-]?\d*\.\d+([eE][+-]?\d+)?$")
    commas = dots = 0
    for row in rows[:200]:
        for cell in row:
            c = cell.strip()
            if comma_num.match(c):
                commas += 1
            elif dot_num.match(c):
                dots += 1
    return "," if commas > dots else "."


def _detect_header(rows: list[list[str]], decimal: str) -> bool:
    """Header if the first row has a non-numeric cell in a column whose data
    rows are predominantly numeric (or if all of row 0 is text and the data
    are not)."""
    if len(rows) < 2:
        return bool(rows) and not all(looks_numeric(c, decimal) for c in rows[0] if c.strip())
    first, body = rows[0], rows[1:51]
    ncol = len(first)
    for j in range(ncol):
        col = [r[j] for r in body if j < len(r) and r[j].strip()]
        if not col:
            continue
        frac = sum(looks_numeric(c, decimal) for c in col) / len(col)
        if frac >= 0.8 and first[j].strip() and not looks_numeric(first[j], decimal):
            return True
    first_text = all(c.strip() and not looks_numeric(c, decimal) for c in first)
    body_text = all(
        all(c.strip() and not looks_numeric(c, decimal) for c in r) for r in body
    )
    return first_text and not body_text


def _unique_names(names: list[str]) -> list[str]:
    out, seen = [], Counter()
    for i, n in enumerate(names):
        n = (n or "").strip() or f"Column_{i + 1}"
        if seen[n]:
            new = f"{n}_{seen[n] + 1}"
            while new in seen:
                new += "_"
            out.append(new)
        else:
            out.append(n)
        seen[n] += 1
    return out


def _default_names(ncol: int, fmt: str) -> list[str]:
    if fmt == "xyz" and ncol >= 2:
        base = ["X", "Y", "Z"][: min(ncol, 3)]
        return base + [f"Column_{i + 1}" for i in range(len(base), ncol)]
    return [f"Column_{i + 1}" for i in range(ncol)]


def _build_frame(rows, opts: ReadOptions, fmt: str, warnings: list[str]):
    header = opts.header
    if header == "auto":
        has_header = _detect_header(rows, opts.decimal or ".")
        opts.header = "yes" if has_header else "no"
    has_header = opts.header == "yes"

    if has_header:
        names_raw, data = rows[0], rows[1:]
    else:
        names_raw, data = None, rows

    ncol = max([len(r) for r in data] + [len(names_raw) if names_raw else 0] + [0])
    if ncol == 0:
        raise DataReadError("The file contains no data rows")
    names = _unique_names(list(names_raw) + [""] * (ncol - len(names_raw))) if names_raw else _default_names(ncol, fmt)

    ragged = 0
    norm = []
    for r in data:
        if len(r) != ncol:
            ragged += 1
            r = list(r[:ncol]) + [""] * (ncol - len(r))
        norm.append([str(c) for c in r])
    if ragged:
        warnings.append(f"{ragged} row(s) had an unexpected number of fields and were padded/truncated")

    total = len(norm)
    truncated = False
    if opts.max_rows is not None and total > opts.max_rows:
        norm = norm[: opts.max_rows]
        truncated = True
    frame = pd.DataFrame(norm, columns=names, dtype=object)
    return frame, total, truncated


def _read_text(path: Path, opts: ReadOptions) -> RawTable:
    warnings: list[str] = []
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DataReadError(f"Cannot read {path.name}: {exc}") from exc
    if b"\x00" in data[:4096]:
        raise DataReadError(f"{path.name} appears to be a binary file, not delimited text")
    text, enc = _decode(data, opts.encoding)
    opts.encoding = enc

    lines = text.splitlines()
    if opts.skip_rows:
        lines = lines[opts.skip_rows:]
    comment = (opts.comment or "").strip()
    content = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if comment and s.startswith(comment):
            continue
        content.append(ln)
    if not content:
        raise DataReadError(f"{path.name} contains no data (after skipping comments/blank lines)")

    if opts.delimiter is None:
        opts.delimiter = _detect_delimiter(content, opts.format or "txt")
    try:
        rows = [_split(ln, opts.delimiter) for ln in content]
    except csv.Error as exc:
        raise DataReadError(f"Parse error in {path.name}: {exc}") from exc

    if opts.decimal is None:
        opts.decimal = _detect_decimal(rows, opts.delimiter)
    if opts.decimal == "," and opts.delimiter == ",":
        raise DataReadError("Decimal comma cannot be used with a comma delimiter")

    frame, total, truncated = _build_frame(rows, opts, opts.format or "txt", warnings)
    return RawTable(frame, opts, opts.format or "txt", total, truncated, warnings)


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------


def _cell_to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    return str(v)


def _read_xlsx(path: Path, opts: ReadOptions) -> RawTable:
    from openpyxl import load_workbook

    warnings: list[str] = []
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise DataReadError(f"Cannot open workbook {path.name}: {exc}") from exc
    try:
        sheets = list(wb.sheetnames)
        sheet = opts.sheet or sheets[0]
        if sheet not in sheets:
            raise DataReadError(f"Sheet {sheet!r} not found. Available: {', '.join(sheets)}")
        opts.sheet = sheet
        ws = wb[sheet]
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i < opts.skip_rows:
                continue
            cells = [_cell_to_str(v) for v in row]
            while cells and cells[-1] == "":
                cells.pop()
            if not cells:
                continue
            if opts.comment and cells[0].strip().startswith(opts.comment):
                continue
            rows.append(cells)
    finally:
        wb.close()
    if not rows:
        raise DataReadError(f"Sheet {opts.sheet!r} in {path.name} contains no data")
    opts.delimiter = None
    opts.encoding = None
    opts.decimal = "."
    frame, total, truncated = _build_frame(rows, opts, "xlsx", warnings)
    return RawTable(frame, opts, "xlsx", total, truncated, warnings, sheets=sheets)


def raw_text_preview(path: str | Path, n_lines: int = 30, encoding: str | None = None) -> str:
    """First lines of a text file, for showing the user the raw source."""
    path = Path(path)
    if detect_format(path) == "xlsx":
        return "(binary Excel workbook - see parsed preview)"
    with open(path, "rb") as fh:
        data = fh.read(256 * 1024)
    text, _ = _decode(data, encoding)
    buf = io.StringIO(text)
    return "".join(buf.readline() for _ in range(n_lines))
