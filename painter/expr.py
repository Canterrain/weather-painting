"""Tiny, safe expression language for `when:` / `amount:` / `opacity:` in scene.yaml.

Supports: numbers, 'strings', true/false, names from the weather state,
and / or / not, comparisons (incl. `in`), + - * /, lists, and these functions:

    ramp(x, lo, hi)   0 at lo, 1 at hi, linear between (clamped)
    clamp(x, lo=0, hi=1)
    min(...), max(...), abs(x), round(x)

Examples:
    "phase == 'night' and moon_up and moon_illum > 0.9"
    "ramp(snow_depth_cm, 0.5, 15)"
    "condition in ['rain', 'drizzle', 'thunderstorm']"
"""

from __future__ import annotations

import ast
import operator


def ramp(x, lo, hi):
    if hi == lo:
        return 1.0 if x >= hi else 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


FUNCS = {"ramp": ramp, "clamp": clamp, "min": min, "max": max, "abs": abs, "round": round}

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod}
_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge,
        ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}


class ExprError(ValueError):
    pass


def evaluate(src, names: dict):
    if isinstance(src, (int, float, bool)):
        return src
    src = str(src)
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"bad expression {src!r}: {e.msg}") from None
    return _eval(tree.body, names, src)


def _eval(n, names, src):
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, ast.Name):
        if n.id in ("True", "true"):
            return True
        if n.id in ("False", "false"):
            return False
        if n.id not in names:
            raise ExprError(f"unknown name {n.id!r} in {src!r}")
        return names[n.id]
    if isinstance(n, ast.BoolOp):
        vals = (_eval(v, names, src) for v in n.values)
        return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.UnaryOp):
        v = _eval(n.operand, names, src)
        if isinstance(n.op, ast.Not):
            return not v
        if isinstance(n.op, ast.USub):
            return -v
        if isinstance(n.op, ast.UAdd):
            return +v
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        return _BIN[type(n.op)](_eval(n.left, names, src), _eval(n.right, names, src))
    if isinstance(n, ast.Compare):
        left = _eval(n.left, names, src)
        for op, right_node in zip(n.ops, n.comparators):
            right = _eval(right_node, names, src)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(n, (ast.List, ast.Tuple)):
        return [_eval(e, names, src) for e in n.elts]
    if isinstance(n, ast.IfExp):
        return _eval(n.body, names, src) if _eval(n.test, names, src) else _eval(n.orelse, names, src)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
        return FUNCS[n.func.id](*[_eval(a, names, src) for a in n.args])
    raise ExprError(f"unsupported syntax in {src!r}")
