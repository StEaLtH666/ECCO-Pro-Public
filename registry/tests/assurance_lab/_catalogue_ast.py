"""Static, import-free evaluation of module-level literal tables in Python source files, for the catalogue generator
gen_catalogue.py (standard library only; test-only helper: no network, no Home Assistant, no hardware; writes nothing).

The lab suites run their scenarios when they are imported, so the generator never imports or executes them. This module
parses a suite's source with ast and evaluates a small, closed subset of expressions: literals, names bound at module
level, attribute access on aliased lab helper modules (for example L.FW_REL), string / list concatenation, subscripts,
f-strings over those values, a whitelist of str / dict methods and of builtins. Later module-level subscript assignments
and .update() calls on a table are applied in source order. Anything outside that subset raises Unresolvable (fail loud:
the generator reports it, it never guesses a value).

API
  Module(path, aliases=None, name=None)   parse one file; aliases maps a module alias used in the file (C, T, L, H, R) to
                                          another Module whose bindings it reads
  Module.has(name) -> bool                a module-level binding exists
  Module.get(name, which="last")          the evaluated value of the last (or "first") binding, post statements applied
  jsonable(value)                         tuples -> lists, sets -> sorted lists, keys -> str (deterministic)
  Unresolvable                            the exception for every construct outside the subset
"""
from __future__ import annotations

import ast
from pathlib import Path


class Unresolvable(Exception):
    pass


_STR_METHODS = {"replace", "split", "strip", "rstrip", "lstrip", "join", "lower", "upper", "startswith", "endswith",
                "format"}
_BUILTINS = {"sorted", "list", "tuple", "dict", "str", "len", "set", "frozenset"}


class Module:
    def __init__(self, path: Path, aliases: dict | None = None, name: str | None = None):
        self.path = Path(path)
        self.name = name or self.path.stem
        self.src = self.path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.tree = ast.parse(self.src)
        self.aliases = dict(aliases or {})          # alias -> Module (for L.FW_REL etc.)
        self.bindings: dict[str, list[tuple[int, ast.AST]]] = {}
        self.post: list[ast.stmt] = []
        for i, node in enumerate(self.tree.body):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.bindings.setdefault(t.id, []).append((i, node.value))
                    elif (isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple)
                          and len(t.elts) == len(node.value.elts)):
                        for te, ve in zip(t.elts, node.value.elts):
                            if isinstance(te, ast.Name):
                                self.bindings.setdefault(te.id, []).append((i, ve))
                    elif isinstance(t, ast.Subscript):
                        self.post.append(node)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                self.bindings.setdefault(node.target.id, []).append((i, node.value))
            elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                  and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "update"):
                self.post.append(node)
        self._cache: dict[str, object] = {}

    # -----------------------------------------------------------------------------------------------------------------
    def has(self, name: str) -> bool:
        return name in self.bindings

    def get(self, name: str, *, which: str = "last"):
        """Value of a module-level name (the last binding by default), with later subscript / update statements on it
        applied in source order."""
        key = f"{name}@{which}"
        if key in self._cache:
            return self._cache[key]
        if name not in self.bindings:
            raise Unresolvable(f"{self.name}: no module-level binding {name!r}")
        idx, node = self.bindings[name][-1 if which == "last" else 0]
        self._cache[key] = None   # recursion guard
        val = self.ev(node)
        for st in self.post:
            if self._post_root(st) == name and self.tree.body.index(st) > idx:
                self._apply_post(st, val)
        self._cache[key] = val
        return val

    def _post_root(self, st) -> str | None:
        node = st.targets[0] if isinstance(st, ast.Assign) else st.value.func.value
        while isinstance(node, (ast.Subscript, ast.Attribute)):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    def _apply_post(self, st, root_val) -> None:
        if isinstance(st, ast.Assign):
            tgt = st.targets[0]
            container = self._walk(tgt.value, root_val)
            container[self.ev(tgt.slice)] = self.ev(st.value)
        else:
            call = st.value
            container = self._walk(call.func.value, root_val)
            if not isinstance(container, dict):
                raise Unresolvable(f"{self.name}: update() on a non-dict")
            for a in call.args:
                container.update(self.ev(a))
            for kw in call.keywords:
                if kw.arg is None:
                    container.update(self.ev(kw.value))
                else:
                    container[kw.arg] = self.ev(kw.value)

    def _walk(self, node, root_val):
        if isinstance(node, ast.Name):
            return root_val
        if isinstance(node, ast.Subscript):
            return self._walk(node.value, root_val)[self.ev(node.slice)]
        raise Unresolvable(f"{self.name}: unsupported post-statement target {ast.unparse(node)}")

    # -----------------------------------------------------------------------------------------------------------------
    def ev(self, node):
        m = getattr(self, "_ev_" + type(node).__name__, None)
        if m is None:
            raise Unresolvable(f"{self.name}:{getattr(node, 'lineno', '?')}: unsupported {type(node).__name__}: "
                               f"{ast.unparse(node)[:120]}")
        return m(node)

    def _ev_Constant(self, n):
        return n.value

    def _ev_Name(self, n):
        if n.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[n.id]
        return self.get(n.id)

    def _ev_List(self, n):
        out = []
        for e in n.elts:
            if isinstance(e, ast.Starred):
                out.extend(self.ev(e.value))
            else:
                out.append(self.ev(e))
        return out

    def _ev_Tuple(self, n):
        return tuple(self._ev_List(n))

    def _ev_Set(self, n):
        return set(self._ev_List(n))

    def _ev_Dict(self, n):
        out = {}
        for k, v in zip(n.keys, n.values):
            if k is None:
                out.update(self.ev(v))
            else:
                out[self.ev(k)] = self.ev(v)
        return out

    def _ev_BinOp(self, n):
        a, b = self.ev(n.left), self.ev(n.right)
        if isinstance(n.op, ast.Add):
            return a + b
        if isinstance(n.op, ast.Mult):
            return a * b
        if isinstance(n.op, ast.Sub) and all(isinstance(x, (int, float)) for x in (a, b)):
            return a - b
        if isinstance(n.op, ast.Mod) and isinstance(a, str):
            return a % b
        raise Unresolvable(f"{self.name}:{n.lineno}: unsupported operator {type(n.op).__name__}")

    def _ev_UnaryOp(self, n):
        v = self.ev(n.operand)
        if isinstance(n.op, ast.USub):
            return -v
        if isinstance(n.op, ast.Not):
            return not v
        raise Unresolvable(f"{self.name}:{n.lineno}: unsupported unary op")

    def _ev_JoinedStr(self, n):
        parts = []
        for v in n.values:
            if isinstance(v, ast.Constant):
                parts.append(v.value)
            else:
                x = self.ev(v.value)
                if v.conversion == ord("r"):
                    x = repr(x)
                elif v.conversion == ord("s"):
                    x = str(x)
                spec = self._ev_JoinedStr(v.format_spec) if v.format_spec is not None else ""
                parts.append(format(x, spec))
        return "".join(parts)

    def _ev_Subscript(self, n):
        base = self.ev(n.value)
        if isinstance(n.slice, ast.Slice):
            lo = self.ev(n.slice.lower) if n.slice.lower else None
            hi = self.ev(n.slice.upper) if n.slice.upper else None
            st = self.ev(n.slice.step) if n.slice.step else None
            return base[lo:hi:st]
        return base[self.ev(n.slice)]

    def _ev_Attribute(self, n):
        if isinstance(n.value, ast.Name) and n.value.id in self.aliases:
            return self.aliases[n.value.id].get(n.attr)
        raise Unresolvable(f"{self.name}:{n.lineno}: unsupported attribute {ast.unparse(n)}")

    def _ev_Call(self, n):
        f = n.func
        if isinstance(f, ast.Attribute) and not (isinstance(f.value, ast.Name) and f.value.id in self.aliases):
            obj = self.ev(f.value)
            args = [self.ev(a) for a in n.args]
            if isinstance(obj, str) and f.attr in _STR_METHODS:
                return getattr(obj, f.attr)(*args)
            if isinstance(obj, dict) and f.attr in ("keys", "values", "items", "get"):
                r = getattr(obj, f.attr)(*args)
                return list(r) if f.attr != "get" else r
            raise Unresolvable(f"{self.name}:{n.lineno}: unsupported method {ast.unparse(f)[:80]}")
        if isinstance(f, ast.Name) and f.id in _BUILTINS:
            args = [self.ev(a) for a in n.args]
            kw = {k.arg: self.ev(k.value) for k in n.keywords}
            return {"sorted": sorted, "list": list, "tuple": tuple, "dict": dict, "str": str, "len": len, "set": set,
                    "frozenset": frozenset}[f.id](*args, **kw)
        raise Unresolvable(f"{self.name}:{n.lineno}: unsupported call {ast.unparse(n)[:120]}")


def jsonable(v):
    """Tuples -> lists, sets -> sorted lists, keys -> str (deterministic)."""
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(jsonable(x) for x in v)
    return v
