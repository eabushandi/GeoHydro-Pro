"""Raster (grid) calculator.

Evaluates an arithmetic expression node by node, for example::

    A - B                     difference of two surfaces (e.g. survey change)
    (A > 2) & (A < 8)         1 where both conditions hold, else 0 (| = or)
    (A - 2.5) * 0.3048        offset then convert feet to metres
    where(A > 10, A, nan)     blank values of 10 or less
    sqrt(A**2 + B**2)         magnitude of two components

Variables ``A``, ``B``, ``C``, ... name the input grids. The expression is
parsed into a syntax tree and only the operators and functions listed below
are allowed; nothing is passed to Python's ``eval``, so an expression cannot
run code or touch files.

All grids must share one CRS. If their geometries differ, the other grids
are resampled to the geometry of ``A`` (bilinear by default) and a warning is
recorded. Blank nodes (NaN) propagate: any operation with a blank input gives
a blank result, except for ``isblank`` and ``fillblank``. Results that are
infinite or undefined (division by zero, log of a non-positive number,
square root of a negative number) are blanked and counted in the warnings;
they are never silently replaced by a number.
"""

from __future__ import annotations

import ast
import operator
import string

import numpy as np

from geohydro.engine.errors import GridMathError
from geohydro.engine.gridding.grid import Grid

from .common import check_crs, derived, resample, same_geometry

_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: np.mod,
           ast.FloorDiv: np.floor_divide}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _logical(fn):
    def f(a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        return np.where(np.isnan(a) | np.isnan(b), np.nan, fn(a > 0, b > 0).astype(float))
    return f


_BINOPS[ast.BitAnd] = _logical(np.logical_and)
_BINOPS[ast.BitOr] = _logical(np.logical_or)
_CMP = {ast.Gt: np.greater, ast.GtE: np.greater_equal, ast.Lt: np.less,
        ast.LtE: np.less_equal, ast.Eq: np.equal, ast.NotEq: np.not_equal}


def _where(cond, a, b):
    c = np.asarray(cond, dtype=float)
    out = np.where(c > 0, a, b).astype(float)
    return np.where(np.isnan(c), np.nan, out)  # a blank condition gives a blank result


FUNCTIONS = {
    "abs": np.abs, "sqrt": np.sqrt, "exp": np.exp, "log": np.log, "ln": np.log,
    "log10": np.log10, "sin": np.sin, "cos": np.cos, "tan": np.tan, "asin": np.arcsin,
    "acos": np.arccos, "atan": np.arctan, "atan2": np.arctan2, "sinh": np.sinh,
    "cosh": np.cosh, "tanh": np.tanh, "floor": np.floor, "ceil": np.ceil,
    "round": np.round, "degrees": np.degrees, "radians": np.radians,
    "min": np.fmin, "max": np.fmax, "minimum": np.minimum, "maximum": np.maximum,
    "where": _where, "isblank": lambda a: np.isnan(a).astype(float),
    "fillblank": lambda a, v: np.where(np.isnan(a), v, a),
    "clip": np.clip,
}
CONSTANTS = {"pi": np.pi, "e": np.e, "nan": np.nan, "blank": np.nan}
VARIABLES = tuple(string.ascii_uppercase)


def parse(expression: str) -> ast.Expression:
    """Parse and validate an expression; raises GridMathError on anything not allowed."""
    if not expression or not expression.strip():
        raise GridMathError("Enter an expression, for example A - B.")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise GridMathError(f"Syntax error in expression at column {exc.offset}: {exc.msg}") \
            from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Load, ast.operator, ast.unaryop, ast.cmpop,
                             ast.boolop)):
            continue
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            continue
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY | {ast.Not: None}:
            continue
        if isinstance(node, ast.Compare) and all(type(o) in _CMP for o in node.ops):
            continue
        if isinstance(node, ast.BoolOp):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name) and (node.id in VARIABLES or node.id in CONSTANTS
                                           or node.id in FUNCTIONS):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in FUNCTIONS and not node.keywords:
            continue
        what = type(node).__name__
        if isinstance(node, ast.Name):
            what = f"name '{node.id}'"
        elif isinstance(node, ast.Call):
            what = "this function call"
        raise GridMathError(f"Not allowed in an expression: {what}. Use grid letters A-Z, "
                            "numbers, + - * / ** %, comparisons and the listed functions.")
    return tree


def variables_used(expression: str) -> list[str]:
    tree = parse(expression)
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
                   and n.id in VARIABLES})


def _eval(node, env):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise GridMathError(f"Grid {node.id} is not assigned.")
    if isinstance(node, ast.BinOp):
        return _BINOPS[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        if isinstance(node.op, ast.Not):
            return np.where(np.isnan(v), np.nan, (np.asarray(v) <= 0).astype(float))
        return _UNARY[type(node.op)](v)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        result = None
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, env)
            r = _CMP[type(op)](left, right).astype(float)
            r = np.where(np.isnan(left) | np.isnan(right), np.nan, r)
            result = r if result is None else np.where(np.isnan(result) | np.isnan(r), np.nan,
                                                       result * r)
            left = right
        return result
    if isinstance(node, ast.BoolOp):
        vals = [np.asarray(_eval(v, env), float) for v in node.values]
        out = vals[0] > 0
        nan = np.isnan(vals[0])
        for v in vals[1:]:
            out = (out & (v > 0)) if isinstance(node.op, ast.And) else (out | (v > 0))
            nan |= np.isnan(v)
        return np.where(nan, np.nan, out.astype(float))
    if isinstance(node, ast.Call):
        fn = FUNCTIONS[node.func.id]
        args = [_eval(a, env) for a in node.args]
        try:
            return fn(*args)
        except TypeError as exc:
            raise GridMathError(f"{node.func.id}(): wrong number of arguments.") from exc
    raise GridMathError(f"Unsupported expression element {type(node).__name__}.")


def calculate(expression: str, grids: dict[str, Grid], name: str | None = None,
              resampling: str = "bilinear", z_units: str | None = None) -> Grid:
    """Evaluate ``expression`` with ``grids`` bound to letters (``{"A": grid, ...}``)."""
    tree = parse(expression)
    used = variables_used(expression)
    if not used:
        raise GridMathError("The expression uses no grid (A, B, ...).")
    missing = [v for v in used if v not in grids]
    if missing:
        raise GridMathError("No grid assigned to " + ", ".join(missing) + ".")
    ref = grids[used[0]] if "A" not in used else grids["A"]
    inputs = [grids[v] for v in used]
    check_crs(inputs)
    warnings = []
    env = {}
    for v in used:
        g = grids[v]
        if not same_geometry(g.geometry, ref.geometry):
            g = resample(g, ref.geometry, resampling)
            warnings.append(f"Grid {v} ('{grids[v].name}') was resampled ({resampling}) to the "
                            f"geometry of '{ref.name}'.")
        env[v] = g.z
    blank_in = np.zeros(ref.geometry.shape, bool)
    for v in used:
        blank_in |= np.isnan(env[v])
    with np.errstate(all="ignore"):
        z = np.asarray(_eval(tree, env), dtype=float)
    if z.shape != ref.geometry.shape:
        z = np.broadcast_to(z, ref.geometry.shape).astype(float)
    bad = ~np.isfinite(z) & ~blank_in
    n_inf = int(np.isinf(z).sum())
    n_undef = int((np.isnan(z) & ~blank_in).sum())
    z = np.where(np.isfinite(z), z, np.nan)
    if n_inf:
        warnings.append(f"{n_inf:,} node(s) gave an infinite result (for example division by "
                        "zero) and were blanked.")
    if n_undef:
        warnings.append(f"{n_undef:,} node(s) gave an undefined result (for example log or "
                        "square root of a negative number, or an explicit blank) and are blank.")
    _ = bad
    out = derived(ref, z, name or expression, "grid_math.calculator",
                  {"expression": expression,
                   "variables": {v: {"id": grids[v].id, "name": grids[v].name} for v in used},
                   "resampling": resampling},
                  warnings, z_units=z_units, sources=inputs)
    out.metadata["method_title"] = f"Grid calculator: {expression}"
    return out
