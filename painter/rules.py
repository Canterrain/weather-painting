"""Compile scene.yaml expressions into postfix tokens the firmware evaluates.

The device can't run Python, so `when` / `amount` / `opacity` expressions are
turned into a flat list of tokens for a tiny stack machine:

    n:<number>   push a number          s:<text>   push a string
    v:<name>     push a state value     o:<op>     operator (pops 1 or 2)
    f:<name>:<argc>  call ramp/clamp/min/max/abs/round
    o:if         pops else, then, test; pushes then if test else else

`x in ['a', 'b']` becomes `x == 'a' or x == 'b'`, so the machine never needs
lists. `eval_tokens` is a Python copy of the firmware's machine, used to check
every compiled rule against the real expression evaluator before publishing.
"""

from __future__ import annotations

import ast

from .expr import FUNCS, ExprError, evaluate

BINOPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Mod: "%"}
CMPOPS = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}


def compile_expr(src, known_names: set[str]) -> list[str]:
    if isinstance(src, bool):
        return [f"n:{int(src)}"]
    if isinstance(src, (int, float)):
        return [f"n:{float(src)!r}"]
    tree = ast.parse(str(src), mode="eval")
    out: list[str] = []
    _emit(tree.body, out, known_names, str(src))
    return out


def _emit(n, out, names, src):
    if isinstance(n, ast.Constant):
        if isinstance(n.value, bool):
            out.append(f"n:{int(n.value)}")
        elif isinstance(n.value, (int, float)):
            out.append(f"n:{float(n.value)!r}")
        elif isinstance(n.value, str):
            if any(c.isspace() for c in n.value):
                raise ExprError(f"strings can't contain spaces on the device: {n.value!r} in {src!r}")
            out.append(f"s:{n.value}")
        else:
            raise ExprError(f"unsupported constant in {src!r}")
    elif isinstance(n, ast.Name):
        if n.id in ("True", "true"):
            out.append("n:1")
        elif n.id in ("False", "false"):
            out.append("n:0")
        elif n.id not in names:
            raise ExprError(f"unknown name {n.id!r} in {src!r}")
        else:
            out.append(f"v:{n.id}")
    elif isinstance(n, ast.BoolOp):
        op = "and" if isinstance(n.op, ast.And) else "or"
        _emit(n.values[0], out, names, src)
        for v in n.values[1:]:
            _emit(v, out, names, src)
            out.append(f"o:{op}")
    elif isinstance(n, ast.UnaryOp):
        _emit(n.operand, out, names, src)
        if isinstance(n.op, ast.Not):
            out.append("o:not")
        elif isinstance(n.op, ast.USub):
            out.append("o:neg")
        elif not isinstance(n.op, ast.UAdd):
            raise ExprError(f"unsupported operator in {src!r}")
    elif isinstance(n, ast.BinOp) and type(n.op) in BINOPS:
        _emit(n.left, out, names, src)
        _emit(n.right, out, names, src)
        out.append(f"o:{BINOPS[type(n.op)]}")
    elif isinstance(n, ast.Compare):
        left = n.left
        for i, (op, right) in enumerate(zip(n.ops, n.comparators)):
            if isinstance(op, (ast.In, ast.NotIn)):
                if not isinstance(right, (ast.List, ast.Tuple)) or not right.elts:
                    raise ExprError(f"'in' needs a literal list on the device: {src!r}")
                for j, item in enumerate(right.elts):
                    _emit(left, out, names, src)
                    _emit(item, out, names, src)
                    out.append("o:==")
                    if j:
                        out.append("o:or")
                if isinstance(op, ast.NotIn):
                    out.append("o:not")
            else:
                _emit(left, out, names, src)
                _emit(right, out, names, src)
                out.append(f"o:{CMPOPS[type(op)]}")
            if i:
                out.append("o:and")
            left = right
    elif isinstance(n, ast.IfExp):
        _emit(n.test, out, names, src)
        _emit(n.body, out, names, src)
        _emit(n.orelse, out, names, src)
        out.append("o:if")
    elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
        for a in n.args:
            _emit(a, out, names, src)
        out.append(f"f:{n.func.id}:{len(n.args)}")
    else:
        raise ExprError(f"unsupported syntax in {src!r}")


def eval_tokens(tokens: list[str], state: dict):
    """Python twin of the firmware's stack machine (see weather_painting/rules.cpp)."""
    st: list = []
    for t in tokens:
        kind, _, arg = t.partition(":")
        if kind == "n":
            st.append(float(arg))
        elif kind == "s":
            st.append(arg)
        elif kind == "v":
            v = state[arg]
            st.append(float(v) if isinstance(v, (bool, int, float)) else v)
        elif kind == "f":
            name, argc = arg.rsplit(":", 1)
            args = st[len(st) - int(argc):]
            del st[len(st) - int(argc):]
            st.append(float(FUNCS[name](*args)))
        elif arg == "not":
            st.append(0.0 if _truthy(st.pop()) else 1.0)
        elif arg == "neg":
            st.append(-st.pop())
        elif arg == "if":
            other, then, test = st.pop(), st.pop(), st.pop()
            st.append(then if _truthy(test) else other)
        else:
            b, a = st.pop(), st.pop()
            st.append(_binop(arg, a, b))
    return st[-1]


def _truthy(v):
    return bool(v) if not isinstance(v, str) else v != ""


def _binop(op, a, b):
    if op == "and":
        return 1.0 if _truthy(a) and _truthy(b) else 0.0
    if op == "or":
        return 1.0 if _truthy(a) or _truthy(b) else 0.0
    if op == "==":
        return 1.0 if a == b else 0.0
    if op == "!=":
        return 1.0 if a != b else 0.0
    if op in ("<", "<=", ">", ">="):
        r = {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        return 1.0 if r else 0.0
    if op == "/":
        return a / b if b else 0.0
    if op == "%":
        return a % b if b else 0.0
    return {"+": a + b, "-": a - b, "*": a * b}[op]


def check(src, tokens, state) -> bool:
    """Does the compiled rule agree with the real evaluator for this state?"""
    want, got = evaluate(src if src is not None else True, state), eval_tokens(tokens, state)
    if isinstance(want, bool):
        return want == _truthy(got)
    return abs(float(want) - float(got)) < 1e-9
