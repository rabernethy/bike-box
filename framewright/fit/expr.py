"""Safe arithmetic expression evaluator for user-editable fit formulas.

Fit schemes (``fit.advisor``) store their formulas as text so riders and
fitters can customise them and share them as JSON.  Those strings come from
files and design documents, so they are never handed to ``eval``.  Instead the
expression is parsed with :mod:`ast` and walked by a small interpreter that
only understands a strict whitelist:

* numbers (``int``/``float``/``bool`` literals; everything is evaluated as float),
* names looked up in the supplied ``variables`` mapping (plus ``pi`` and ``e``),
* ``+ - * / // % **``, unary ``+``/``-``, ``not``, ``and``/``or``,
* comparisons (``< <= > >= == !=``, chained),
* conditional expressions ``a if cond else b``,
* calls to ``min max abs round sqrt sin cos tan asin acos atan atan2 clamp lerp``
  (trigonometry works in **degrees**), plus any extra trusted callables the
  caller passes explicitly through ``functions``.

Everything else (attribute access, subscripts, lambdas, comprehensions,
strings, keyword/star arguments, dunder names, any other call) is rejected
before evaluation.  Numbers are evaluated as floats, so ``9**9**9`` overflows
with an error instead of building a huge integer.
"""
from __future__ import annotations

import ast
import math
import operator
from typing import Any, Callable, Mapping

MAX_LENGTH = 4000          # characters
MAX_NODES = 600            # AST nodes
MAX_POW_EXPONENT = 1000.0


class ExprError(ValueError):
    """Raised for invalid, unsafe or failing expressions."""


def _clamp(x: float, lo: float, hi: float) -> float:
    if lo > hi:
        lo, hi = hi, lo
    return min(max(x, lo), hi)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _round(x: float, n: float = 0) -> float:
    return float(round(x, int(n)))


FUNCTIONS: dict[str, Callable[..., float]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": _round,
    "sqrt": math.sqrt,
    "sin": lambda a: math.sin(math.radians(a)),
    "cos": lambda a: math.cos(math.radians(a)),
    "tan": lambda a: math.tan(math.radians(a)),
    "asin": lambda x: math.degrees(math.asin(x)),
    "acos": lambda x: math.degrees(math.acos(x)),
    "atan": lambda x: math.degrees(math.atan(x)),
    "atan2": lambda y, x: math.degrees(math.atan2(y, x)),
    "clamp": _clamp,
    "lerp": _lerp,
}
# (min arity, max arity)
_ARITY = {"min": (1, 64), "max": (1, 64), "abs": (1, 1), "round": (1, 2), "sqrt": (1, 1),
          "sin": (1, 1), "cos": (1, 1), "tan": (1, 1), "asin": (1, 1), "acos": (1, 1), "atan": (1, 1),
          "atan2": (2, 2), "clamp": (3, 3), "lerp": (3, 3)}

CONSTANTS = {"pi": math.pi, "e": math.e}

_BINOPS: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_CMPOPS: dict[type, Callable[[float, float], bool]] = {
    ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.Eq: operator.eq, ast.NotEq: operator.ne,
}
_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call,
                  ast.Name, ast.Load, ast.Constant, ast.And, ast.Or, ast.Not, ast.UAdd, ast.USub,
                  *_BINOPS, *_CMPOPS)


def _parse(expr: str) -> ast.Expression:
    if not isinstance(expr, str):
        raise ExprError("expression must be text")
    text = expr.strip()
    if not text:
        raise ExprError("empty expression")
    if len(text) > MAX_LENGTH:
        raise ExprError(f"expression longer than {MAX_LENGTH} characters")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"syntax error: {exc.msg}") from None
    except (ValueError, RecursionError, MemoryError):
        raise ExprError("expression cannot be parsed") from None
    return tree


def _check(tree: ast.Expression, functions: Mapping[str, Callable] | None = None) -> list[str]:
    """Structural whitelist check.  Returns a list of problems (empty = safe)."""
    errors: list[str] = []
    allowed_calls = set(FUNCTIONS) | set(functions or {})
    count = 0
    for node in ast.walk(tree):
        count += 1
        if count > MAX_NODES:
            errors.append(f"expression too complex (more than {MAX_NODES} nodes)")
            break
        if not isinstance(node, _ALLOWED_NODES):
            errors.append(f"{type(node).__name__} is not allowed")
            continue
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool) or (isinstance(v, (int, float)) and not isinstance(v, complex)):
                continue
            errors.append(f"constant {v!r} is not a number")
        elif isinstance(node, ast.Name):
            if "__" in node.id or node.id.startswith("_"):
                errors.append(f"name {node.id!r} is not allowed")
            elif not isinstance(node.ctx, ast.Load):
                errors.append(f"assignment to {node.id!r} is not allowed")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                errors.append("only direct calls to whitelisted functions are allowed")
                continue
            name = node.func.id
            if name not in allowed_calls:
                errors.append(f"function {name!r} is not allowed")
                continue
            if node.keywords:
                errors.append(f"keyword arguments to {name}() are not allowed")
            if any(isinstance(a, ast.Starred) for a in node.args):
                errors.append(f"star arguments to {name}() are not allowed")
            if name in _ARITY and not (functions and name in functions):
                lo, hi = _ARITY[name]
                if not lo <= len(node.args) <= hi:
                    errors.append(f"{name}() takes {lo if lo == hi else f'{lo}-{hi}'} argument(s), "
                                  f"got {len(node.args)}")
    return errors


def validate(expr: str, names: Mapping[str, Any] | set[str] | None = None,
             functions: Mapping[str, Callable] | None = None) -> list[str]:
    """Return a list of error messages; empty if ``expr`` is a safe, well-formed
    formula.  When ``names`` is given, unknown variable names are reported too."""
    try:
        tree = _parse(expr)
    except ExprError as exc:
        return [str(exc)]
    errors = _check(tree, functions)
    if names is not None and not errors:
        known = set(names) | set(CONSTANTS)
        call_names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and n.id not in known and n.id not in call_names:
                errors.append(f"unknown name {n.id!r}")
    return errors


def names_used(expr: str) -> set[str]:
    """Variable names referenced by ``expr`` (function names excluded)."""
    tree = _parse(expr)
    calls = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and id(n) not in calls}


class _Interpreter:
    def __init__(self, variables: Mapping[str, Any], functions: Mapping[str, Callable] | None):
        self.vars = variables
        self.funcs = dict(FUNCTIONS)
        if functions:
            self.funcs.update(functions)

    def run(self, node: ast.AST) -> Any:
        m = getattr(self, "_" + type(node).__name__, None)
        if m is None:                       # unreachable after _check, kept as a second guard
            raise ExprError(f"{type(node).__name__} is not allowed")
        return m(node)

    def num(self, node: ast.AST) -> float:
        v = self.run(node)
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if not isinstance(v, (int, float)):
            raise ExprError("value is not a number")
        return float(v)

    def _Expression(self, node: ast.Expression) -> Any:
        return self.run(node.body)

    def _Constant(self, node: ast.Constant) -> float:
        v = node.value
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, (int, float)):
            return float(v)
        raise ExprError(f"constant {v!r} is not a number")

    def _Name(self, node: ast.Name) -> float:
        name = node.id
        if "__" in name or name.startswith("_"):
            raise ExprError(f"name {name!r} is not allowed")
        if name in self.vars:
            v = self.vars[name]
        elif name in CONSTANTS:
            v = CONSTANTS[name]
        else:
            raise ExprError(f"unknown name {name!r}")
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ExprError(f"variable {name!r} is not a number") from None

    def _BinOp(self, node: ast.BinOp) -> float:
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ExprError(f"operator {type(node.op).__name__} is not allowed")
        a = self.num(node.left)
        b = self.num(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > MAX_POW_EXPONENT:
            raise ExprError("exponent too large")
        return float(op(a, b))

    def _UnaryOp(self, node: ast.UnaryOp) -> float:
        if isinstance(node.op, ast.Not):
            return 0.0 if self.num(node.operand) else 1.0
        v = self.num(node.operand)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        raise ExprError(f"operator {type(node.op).__name__} is not allowed")

    def _BoolOp(self, node: ast.BoolOp) -> float:
        if isinstance(node.op, ast.And):
            v = 1.0
            for n in node.values:
                v = self.num(n)
                if not v:
                    return v
            return v
        v = 0.0
        for n in node.values:
            v = self.num(n)
            if v:
                return v
        return v

    def _Compare(self, node: ast.Compare) -> float:
        left = self.num(node.left)
        for op_node, right_node in zip(node.ops, node.comparators):
            op = _CMPOPS.get(type(op_node))
            if op is None:
                raise ExprError(f"comparison {type(op_node).__name__} is not allowed")
            right = self.num(right_node)
            if not op(left, right):
                return 0.0
            left = right
        return 1.0

    def _IfExp(self, node: ast.IfExp) -> float:
        return self.num(node.body) if self.num(node.test) else self.num(node.orelse)

    def _Call(self, node: ast.Call) -> float:
        if not isinstance(node.func, ast.Name) or node.func.id not in self.funcs:
            raise ExprError("function is not allowed")
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            raise ExprError("only positional arguments are allowed")
        args = [self.num(a) for a in node.args]
        return float(self.funcs[node.func.id](*args))


def evaluate(expr: str, variables: Mapping[str, Any] | None = None,
             functions: Mapping[str, Callable[..., float]] | None = None) -> float:
    """Evaluate ``expr`` with ``variables`` and return a float.

    ``functions`` may add trusted, caller-supplied callables (the fit advisor
    uses this for model helpers such as ``kops_setback(h)``); it can never make
    Python builtins reachable from the expression text.  Raises
    :class:`ExprError` for anything invalid, unsafe or failing (unknown names,
    division by zero, domain errors, overflow).
    """
    tree = _parse(expr)
    errors = _check(tree, functions)
    if errors:
        raise ExprError("; ".join(errors))
    try:
        result = _Interpreter(variables or {}, functions).num(tree)
    except ExprError:
        raise
    except ZeroDivisionError:
        raise ExprError("division by zero") from None
    except OverflowError:
        raise ExprError("numeric overflow") from None
    except (ValueError, TypeError) as exc:
        raise ExprError(f"math error: {exc}") from None
    except RecursionError:
        raise ExprError("expression nested too deeply") from None
    if not math.isfinite(result):
        raise ExprError("result is not a finite number")
    return result
