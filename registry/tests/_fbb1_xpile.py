"""FB-B1 transpiler extensions for the strict FB-B simulator (mixed into
_fbb_harness.FbbTranspiler; _dump_sim.Transpiler itself is unchanged).

What _dump_sim's C++-subset transpiler lacked and the FB-B1 lambdas may use
(each is covered, with a negative control, by test_fallback_capture_harness.py):

  * std::array<T, N> locals / `T name[N]` / `T name[] = {...}` as bounds-checked
    FbArray values (zero-initialised), brace and `= expr` initialisation,
    references (`T &r = id(g);` aliases, `const auto &x`), `auto` copies
  * `id(g)[i]` reads and stores for std::array globals
  * casts `(uint8_t) (uint16_t) (uint32_t) (uint64_t) (int) (unsigned long)
    (unsigned long long) (bool) ...`, `static_cast<T>(x)`
  * uint32_t / uint64_t VALUES that wrap (millis() - x, typed globals / locals,
    casts): C's unsigned arithmetic, so TTL / age arithmetic is wrap-safe
  * `constexpr` / `static const` locals, uninitialised local arrays
  * `while`, `do ... while`, `for (init; cond; step)`, `continue`, `break`
  * compound assignment `^= *= /= %= <<= >>=`, prefix / postfix `++ --`
  * `~x`, unary `+`, `sizeof(type | local array | id(array) | char buffer)`
  * `std::to_string`, `std::string::npos`, std::string concatenation that
    stays a std::string, `.substr / .find / .compare / .length`
  * `static_assert(cond, "msg");` evaluated at run time
  * `random_uint32()`, `millis()`, `millis_64()` typed as unsigned
  * FB-B2: the mutating std::string members as statements (`s.assign(x); s.append(x); s.clear(); s.push_back(c);
    s.pop_back(); s.erase(p, n); s.resize(n); s.insert(p, x);` on a std::string global or local - Python strings are
    immutable, so each becomes an assignment of `str_mut(op, s, args...)`), `std::string(ptr, n)` / `std::string s(ptr, n)`
    / `std::string(StringRef)`, and the `ecco_fbsave::` namespace's template-argument drop (like ecco_fbcap::)

Anything else raises FbbNotModelled at translate time - including an
identifier that is not a declared local / parameter ("using namespace" is not
modelled: FB code must qualify every ecco_* name), a `static` local, a
`(char)` cast, `reinterpret_cast`, pointer arithmetic.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dump_sim as ds  # noqa: E402
from _fbb1_types import (ARRAY_ELEM_TYPES, CTYPE_SIZEOF, FbbNotModelled, UNSIGNED_CTYPES, parse_array_ctype)  # noqa: E402

# type phrases a C cast / static_cast may name -> canonical C type
_CAST_PHRASES = {
    ("uint8_t",): "uint8_t", ("uint16_t",): "uint16_t", ("uint32_t",): "uint32_t", ("uint64_t",): "uint64_t",
    ("int8_t",): "int8_t", ("int16_t",): "int16_t", ("int32_t",): "int32_t", ("int64_t",): "int64_t",
    ("int",): "int", ("unsigned",): "unsigned", ("unsigned", "int"): "unsigned", ("unsigned", "long"): "unsigned long",
    ("unsigned", "long", "long"): "unsigned long long", ("long",): "long", ("long", "long"): "long long",
    ("size_t",): "size_t", ("float",): "float", ("double",): "double", ("bool",): "bool",
}
_TYPE_WORDS = {"unsigned", "signed", "long", "short", "int", "char"}
_SCALAR_DECL = {"bool", "int", "uint8_t", "uint16_t", "uint32_t", "int32_t", "float", "double", "auto", "char", "unsigned",
                "size_t", "uint64_t", "int8_t", "int16_t", "int64_t", "long", "signed", "short"}
# identifiers the base transpiler's primary() consumes itself
_BASE_PRIMARY_IDS = {"ecco_recovery_evidence", "ecco_durable", "std", "lroundf", "snprintf", "true", "false", "NAN", "id"}
_LAMBDA_NAMES = "lambda"


def incdec_l(L, name, delta, post, ctype):
    old = L[name]
    new = ds.wrap(old + delta, ctype) if ctype else old + delta
    L[name] = new
    return old if post else new


def incdec_idx(container, idx, delta, post):
    old = container[idx]
    container[idx] = old + delta
    return old if post else container[idx]


def c_to_string(v):
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return str(int(v))
    raise FbbNotModelled("std::to_string of a non-integer (C++ prints with %f)")


def static_assert_fail(msg):
    raise AssertionError(f"static_assert failed: {msg}")


class XpileMixin:
    """Mixed in BEFORE ds.Transpiler (see _fbb_harness.FbbTranspiler)."""

    def _xinit(self, array_globals=None):
        self.array_globals = dict(array_globals or {})
        self.arrays: dict = {}
        self.refs: set = set()
        self.loop_stack: list = []
        self._loop_id = 0
        self._last_const = False

    # ------------------------------------------------------------------ types
    def parse_type(self):
        self._last_const = False
        static = False
        while self.val() in ("const", "constexpr", "static", "volatile"):
            q = self.take()[1]
            if q == "volatile":
                raise FbbNotModelled("volatile")
            if q == "static":
                static = True
            else:
                self._last_const = True
        if static and not self._last_const:
            raise FbbNotModelled("a `static` local keeps state across lambda invocations - not modelled")
        v = self.val()
        if v == "std":
            self.take("std")
            self.take("::")
            name = self.take()[1]
            if name == "string":
                base = "std::string"
            elif name == "array":
                self.take("<")
                elem = self._type_phrase_until((",",))
                self.take(",")
                tok = self.take()
                if tok[0] != "num":
                    raise FbbNotModelled("std::array with a non-literal size")
                self.take(">")
                base = f"std::array<{elem},{int(tok[1].rstrip('uUlL'))}>"
                if parse_array_ctype(base) is None:
                    raise FbbNotModelled(f"{base}: element type is not modelled")
            else:
                raise FbbNotModelled(f"std::{name} as a type")
        elif v == "ecco_durable":
            self.take("ecco_durable")
            self.take("::")
            base = "ecco_durable::" + self.take()[1]
            if self.val() == "<" and base.startswith(("ecco_durable::FBC__", "ecco_durable::FBSV__", "ecco_durable::FBSH__")):
                # `ecco_fbcap::TextBuf<256>`: numeric template arguments of a header type are dropped (the
                # Python mirror class is constructed with its defaults) - documented limit
                self.take("<")
                while self.val() != ">":
                    if self.peek()[0] != "num":
                        raise FbbNotModelled(f"{base}: only numeric template arguments are modelled")
                    self.take()
                    if self.val() == ",":
                        self.take(",")
                self.take(">")
        elif v in ("unsigned", "signed", "long", "short"):
            base = self._multiword_type()
        else:
            base = self.take()[1]
        while self.val() == "*":
            self.take("*")
            base += "*"
        return base

    def _multiword_type(self):
        words = []
        while self.val() in _TYPE_WORDS and (self.peek(1)[0] == "id" or self.val(1) in (")", "&", "*", ">", ",")
                                             or self.val(1) in _TYPE_WORDS):
            words.append(self.take()[1])
        phrase = tuple(words)
        if phrase not in _CAST_PHRASES:
            raise FbbNotModelled(f"C type {' '.join(words)!r} is not modelled")
        return _CAST_PHRASES[phrase]

    def _type_phrase_until(self, stops):
        words = []
        while self.val() not in stops and self.val() is not None:
            words.append(self.take()[1])
        phrase = tuple(w for w in words if w not in ("const",))
        canon = _CAST_PHRASES.get(phrase)
        if canon is None:
            raise FbbNotModelled(f"type {' '.join(words)!r} is not modelled in a cast / template argument")
        return canon

    def is_decl(self):
        v = self.val()
        if v in ("const", "constexpr", "static", "volatile"):
            return True
        if v in _SCALAR_DECL and (self.peek(1)[0] == "id" or self.val(1) in ("*", "&")):
            return True
        if v == "std" and self.val(1) == "::":
            if self.val(2) == "array":
                return True
            if self.val(2) == "string" and (self.peek(3)[0] == "id" or self.val(3) in ("&", "*")):
                return True
        if v == "ecco_durable" and self.val(1) == "::":
            j = 3
            if self.val(j) == "<":  # numeric template arguments of a header type
                while self.val(j) not in (">", None):
                    j += 1
                j += 1
            return self.peek(j)[0] == "id" or self.val(j) == "&"
        return False

    # ------------------------------------------------------------ declarations
    @staticmethod
    def wrap_expr(e, ctype):
        base = ctype.replace("*", "")
        if base == "auto":
            return f"D.FB_copy({e})"
        arr = parse_array_ctype(base)
        if arr is not None:
            return f"mkarr({arr[0]!r}, {arr[1]}, {e})"
        return ds.Transpiler.wrap_expr(e, ctype)

    def decl(self, depth):
        start = self.i
        ctype = self.parse_type()
        const = self._last_const
        ref = False
        if self.val() == "&":
            self.take("&")
            ref = True
        arr = parse_array_ctype(ctype)
        base_ct = ctype.replace("*", "")
        # `auto f = [](...) {...}` - the base transpiler owns lambda definitions.
        if ctype == "auto" and not ref and self.peek(0)[0] == "id" and self.val(1) == "=" and self.val(2) == "[":
            self.i = start
            return ds.Transpiler.decl(self, depth)
        while True:
            name = self.take()[1]
            if not re.fullmatch(r"[A-Za-z_]\w*", name):
                raise FbbNotModelled(f"declaration of {name!r}")
            if self.val() == "[":  # C array
                self._array_declarator(depth, ctype, name)
            elif self.val() == "{":  # brace init
                self.take("{")
                args = []
                while self.val() != "}":
                    args.append(self.expr())
                    if self.val() == ",":
                        self.take(",")
                self.take("}")
                self._init_with_list(depth, ctype, arr, name, args, ref)
            elif self.val() == "(" and arr is None and not ref and (ctype == "std::string" or ctype in _SCALAR_DECL):
                # direct initialisation: `std::string s(buf);` / `uint32_t n(5);`
                self.take("(")
                args = []
                while self.val() != ")":
                    args.append(self.expr())
                    if self.val() == ",":
                        self.take(",")
                self.take(")")
                self._init_with_list(depth, ctype, arr, name, args, ref)
            elif self.val() == "=":
                self.take("=")
                if arr is not None and self.val() == "{":
                    self.take("{")
                    args = []
                    while self.val() != "}":
                        args.append(self.expr())
                        if self.val() == ",":
                            self.take(",")
                    self.take("}")
                    self._init_with_list(depth, ctype, arr, name, args, ref)
                else:
                    e = self.expr()
                    self._init_with_expr(depth, ctype, name, e, ref, const)
            else:
                if ref:
                    raise FbbNotModelled(f"reference {name!r} without an initialiser")
                self._init_default(depth, ctype, arr, name)
            if self.val() == ",":
                self.take(",")
                continue
            self.take(";")
            return

    def _array_declarator(self, depth, ctype, name):
        self.take("[")
        dim = self.expr() if self.val() != "]" else None
        self.take("]")
        if ctype == "char":  # char buffer: keep the base model (CStr rebound by snprintf)
            if dim is not None and dim.isdigit():
                self.char_array_sizes[name] = int(dim)
            if self.val() == "=":
                raise FbbNotModelled("char array initialiser")
            self.emit(depth, f"L[{name!r}] = CStr('')")
            self.ltypes[name] = "char"
            return
        if ctype not in ARRAY_ELEM_TYPES:
            raise FbbNotModelled(f"array of {ctype!r} is not modelled")
        if self.val() == "=":
            self.take("=")
            self.take("{")
            elems = []
            while self.val() != "}":
                elems.append(self.expr())
                if self.val() == ",":
                    self.take(",")
            self.take("}")
            size = dim if dim is not None else str(len(elems))
            self.emit(depth, f"L[{name!r}] = FbArray({ctype!r}, {size}, [{', '.join(elems)}])")
        else:
            if dim is None:
                raise FbbNotModelled(f"array {name!r} without a size")
            self.emit(depth, f"L[{name!r}] = FbArray({ctype!r}, {dim})")
        self.ltypes[name] = ctype + "[]"
        self.arrays[name] = ctype

    def _init_with_list(self, depth, ctype, arr, name, args, ref):
        if ref:
            raise FbbNotModelled("reference bound to a brace list")
        if arr is not None:
            self.emit(depth, f"L[{name!r}] = FbArray({arr[0]!r}, {arr[1]}, [{', '.join(args)}])")
            self.ltypes[name] = ctype
            self.arrays[name] = arr[0]
            return
        if ctype.startswith("ecco_durable::"):
            self.emit(depth, f"L[{name!r}] = D.{ctype.split('::')[1]}({', '.join(args)})")
            self.ltypes[name] = ctype
            return
        if ctype == "std::string":
            if len(args) > 2:
                raise FbbNotModelled("std::string constructed from more than two arguments")
            self.emit(depth, f"L[{name!r}] = " + (f"str_from({', '.join(args)})" if len(args) == 2
                                                  else f"CStr({args[0] if args else repr('')})"))
            self.ltypes[name] = ctype
            return
        if ctype in _SCALAR_DECL and ctype not in ("auto", "char"):
            if len(args) > 1:
                raise FbbNotModelled(f"scalar {name!r} brace-initialised with {len(args)} values")
            self.emit(depth, f"L[{name!r}] = {self.wrap_expr(args[0], ctype) if args else self.wrap_expr('0', ctype)}")
            self.ltypes[name] = ctype
            return
        raise FbbNotModelled(f"brace-init of {ctype}")

    def _init_with_expr(self, depth, ctype, name, e, ref, const):
        base_ct = ctype.replace("*", "")
        if ref:
            if base_ct in _SCALAR_DECL and base_ct != "auto" and "*" not in ctype:
                if not const:
                    raise FbbNotModelled(f"non-const reference to a scalar ({name!r}): a Python int cannot be aliased")
                self.emit(depth, f"L[{name!r}] = {self.wrap_expr(e, ctype)}")
            else:
                self.emit(depth, f"L[{name!r}] = {e}")
                self.refs.add(name)
            self.ltypes[name] = ctype
            return
        self.ltypes[name] = ctype
        self.emit(depth, f"L[{name!r}] = {self.wrap_expr(e, ctype)}")
        if parse_array_ctype(ctype):
            self.arrays[name] = parse_array_ctype(ctype)[0]

    def _init_default(self, depth, ctype, arr, name):
        self.ltypes[name] = ctype
        if arr is not None:
            self.emit(depth, f"L[{name!r}] = FbArray({arr[0]!r}, {arr[1]})")
            self.arrays[name] = arr[0]
        elif ctype.startswith("ecco_durable::"):
            self.emit(depth, f"L[{name!r}] = D.{ctype.split('::')[1]}()")
        elif ctype == "std::string":
            self.emit(depth, f"L[{name!r}] = CStr('')")  # default-constructed: empty
        else:
            self.emit(depth, f"L[{name!r}] = None")

    # -------------------------------------------------------------- statements
    def stmt(self, depth):
        v = self.val()
        if v == "using":
            raise FbbNotModelled("`using` declarations are not modelled: qualify every ecco_* name")
        if v == "while":
            return self._while(depth)
        if v == "do":
            return self._do_while(depth)
        if v == "for":
            return self._for(depth)
        if v == "continue":
            self.take("continue")
            self.take(";")
            loops = [f for f in self.loop_stack if not f.get("switch")]
            if not loops:
                raise FbbNotModelled("`continue` outside a loop")
            fr = loops[-1]  # a switch does not capture `continue`: it belongs to the enclosing loop
            self.emit(depth, "continue" if fr["native"] else "break")
            return
        if v == "break":
            self.take("break")
            self.take(";")
            if not self.loop_stack or self.loop_stack[-1].get("switch"):
                raise FbbNotModelled("`break` that is neither a loop exit nor the end of a switch clause (a break nested "
                                     "inside another statement of a switch clause is not modelled)")
            fr = self.loop_stack[-1]
            if fr["native"]:
                self.emit(depth, "break")
            else:
                self.emit(depth, f"__brk{fr['id']} = True")
                self.emit(depth, "break")
            return
        if v == "static_assert":
            self.take("static_assert")
            self.take("(")
            cond = self.expr()
            msg = "''"
            if self.val() == ",":
                self.take(",")
                msg = self.expr()
            self.take(")")
            self.take(";")
            self.emit(depth, f"if not ({cond}):")
            self.emit(depth + 1, f"static_assert_fail({msg})")
            return
        return super().stmt(depth)

    def switch(self, depth):
        """_dump_sim's switch (integer labels, no fall-through) plus a clause whose body is a
        `{ ... break; }` block - `default: { char buf[32]; snprintf(...); break; }`."""
        self.take("switch")
        self.take("(")
        subject = self.expr()
        self.take(")")
        self.take("{")
        self.loop_stack.append({"switch": True})
        tmp = f"__switch_{self.i}"
        self.emit(depth, f"L[{tmp!r}] = {subject}")
        clauses, labels = [], []
        while self.val() != "}":
            if self.val() == "case":
                self.take("case")
                labels.append(self.expr())
                self.take(":")
                continue
            if self.val() == "default":
                self.take("default")
                self.take(":")
                labels.append(None)
                continue
            if not labels:
                raise FbbNotModelled("switch: statement before any case label")
            saved, self.lines = self.lines, []
            last_kw, ended = None, False
            while self.val() not in ("break", "case", "default", "}"):
                last_kw = self.val()
                if self.val() == "{":
                    self.take("{")
                    while self.val() not in ("}", "break"):
                        last_kw = self.val()
                        self.stmt(depth + 1)
                    if self.val() == "break":
                        self.take("break")
                        self.take(";")
                        ended = True
                    self.take("}")
                    if ended:
                        break
                else:
                    self.stmt(depth + 1)
            if not ended:
                if self.val() == "break":
                    self.take("break")
                    self.take(";")
                elif last_kw not in ("return", "continue"):
                    raise FbbNotModelled("switch: fall-through (clause does not end in break / return / continue)")
            body, self.lines = self.lines or ["    " * (depth + 1) + "pass"], saved
            clauses.append((labels, body))
            labels = []
        if labels:
            raise FbbNotModelled("switch: trailing label without a body")
        self.loop_stack.pop()
        self.take("}")
        first = True
        for lbls, body in [c for c in clauses if None not in c[0]] + [c for c in clauses if None in c[0]]:
            if None in lbls:
                self.emit(depth, "else:" if not first else "if True:")
            else:
                cond = " or ".join(f"L[{tmp!r}] == ({k})" for k in lbls)
                self.emit(depth, f"{'if' if first else 'elif'} {cond}:")
            self.lines.extend(body)
            first = False

    def _new_frame(self, native=False):
        self._loop_id += 1
        fr = {"id": self._loop_id, "native": native}
        self.loop_stack.append(fr)
        return fr

    def _loop_body(self, depth, fr):
        """Emits `once-for` wrapper so `continue` can leave the body while
        the step still runs, and `break` leaves the loop via a flag."""
        self.emit(depth, f"__brk{fr['id']} = False")
        self.emit(depth, f"for __once{fr['id']} in (1,):")
        self.block_or_stmt(depth + 1)
        self.emit(depth, f"if __brk{fr['id']}:")
        self.emit(depth + 1, "break")

    def _while(self, depth):
        self.take("while")
        self.take("(")
        cond = self.expr()
        self.take(")")
        fr = self._new_frame()
        self.emit(depth, "while True:")
        self.emit(depth + 1, f"if not ({cond}):")
        self.emit(depth + 2, "break")
        self._loop_body(depth + 1, fr)
        self.loop_stack.pop()

    def _do_while(self, depth):
        self.take("do")
        fr = self._new_frame()
        self.emit(depth, "while True:")
        self._loop_body(depth + 1, fr)
        self.loop_stack.pop()
        self.take("while")
        self.take("(")
        cond = self.expr()
        self.take(")")
        self.take(";")
        self.emit(depth + 1, f"if not ({cond}):")
        self.emit(depth + 2, "break")

    def _for(self, depth):
        self.take("for")
        self.take("(")
        if self.is_range_for():
            fr = self._new_frame(native=True)
            self.range_for(depth)
            self.loop_stack.pop()
            return
        # init
        if self.val() == ";":
            self.take(";")
        elif self.is_decl():
            self.decl(depth)
        else:
            self.expr_stmt(depth)
        cond = "True"
        if self.val() != ";":
            cond = self.expr()
        self.take(";")
        step_lines = []
        if self.val() != ")":
            saved, self.lines = self.lines, []
            self._step_stmt(depth + 1)
            step_lines, self.lines = self.lines, saved
        self.take(")")
        fr = self._new_frame()
        self.emit(depth, "while True:")
        self.emit(depth + 1, f"if not ({cond}):")
        self.emit(depth + 2, "break")
        self._loop_body(depth + 1, fr)
        self.lines.extend(step_lines)
        self.loop_stack.pop()

    def _step_stmt(self, depth):
        """The step of a for-loop: an assignment / increment without `;`."""
        if self.val() in ("++", "--"):
            op = self.take()[1]
            target = self.lvalue()
            self.emit(depth, self.assign(target, f"({target[1]}) {'+' if op == '++' else '-'} 1"))
            return
        target = self.lvalue()
        op = self.val()
        if op in ("++", "--"):
            self.take()
            self.emit(depth, self.assign(target, f"({target[1]}) {'+' if op == '++' else '-'} 1"))
            return
        if op in ("=", "+=", "-=", "|=", "&=", "^=", "*=", "/=", "%=", "<<=", ">>="):
            self.take()
            rhs = self.expr()
            if op != "=":
                rhs = self._compound(target[1], op[:-1], rhs)
            self.emit(depth, self.assign(target, rhs))
            return
        raise FbbNotModelled("unsupported for-loop step")

    @staticmethod
    def _compound(read, binop, rhs):
        if binop == "/":
            return f"c_div(({read}), ({rhs}))"
        if binop == "%":
            return f"c_mod(({read}), ({rhs}))"
        return f"({read}) {binop} ({rhs})"

    _STR_MUTATORS = ("assign", "append", "clear", "push_back", "pop_back", "erase", "resize", "insert", "reserve",
                     "shrink_to_fit", "replace", "swap")

    def _str_mutator_stmt(self, depth):
        """`id(g).append(x);` / `local.assign(x);` on a std::string global / local -> `target = str_mut(op, target, x)`."""
        if (self.val() == "id" and self.val(1) == "(" and self.val(3) == ")" and self.val(4) == "."
                and self.val(5) in self._STR_MUTATORS and self.val(6) == "("):
            name = self.val(2)
            if self.gtypes.get(name) != "std::string":
                return False
            target, skip = ("global", f"S.g[{name!r}]", name), 6
        elif self.peek()[0] == "id" and self.val(1) == "." and self.val(2) in self._STR_MUTATORS and self.val(3) == "(":
            name = self.val()
            if self.ltypes.get(name) != "std::string":
                return False
            if name in self.refs:
                raise FbbNotModelled(f"{self.val(2)}() through a reference to a std::string ({name!r}) is not modelled")
            target, skip = ("local", f"L[{name!r}]", name), 3
        else:
            return False
        op = self.val(skip - 1)
        self.i += skip
        self.take("(")
        args = []
        while self.val() != ")":
            args.append(self.expr())
            if self.val() == ",":
                self.take(",")
        self.take(")")
        self.take(";")
        self.emit(depth, self.assign(target, f"str_mut({op!r}, {target[1]}{''.join(', ' + a for a in args)})"))
        return True

    def expr_stmt(self, depth):
        start = self.i
        if self._str_mutator_stmt(depth):
            return
        if self.val() in ("++", "--"):
            op = self.take()[1]
            target = self.lvalue()
            self.take(";")
            self.emit(depth, self.assign(target, f"({target[1]}) {'+' if op == '++' else '-'} 1"))
            return
        target = self.lvalue()
        op = self.val()
        if op in ("=", "+=", "-=", "|=", "&=", "^=", "*=", "/=", "%=", "<<=", ">>="):
            self.take()
            rhs = self.expr()
            self.take(";")
            if op != "=":
                rhs = self._compound(target[1], op[:-1], rhs)
            self.emit(depth, self.assign(target, rhs))
            return
        if op in ("++", "--"):
            self.take()
            self.take(";")
            self.emit(depth, self.assign(target, f"({target[1]}) {'+' if op == '++' else '-'} 1"))
            return
        self.i = start
        e = self.expr()
        self.take(";")
        self.emit(depth, e)

    def lvalue(self):
        if (self.val() == "id" and self.val(1) == "(" and self.val(3) == ")" and self.val(2) in self.array_globals
                and self.val(4) == "["):
            name = self.val(2)
            self.i += 5
            idx = self.expr()
            self.take("]")
            return ("gindex", f"S.g[{name!r}][{idx}]", (name, idx))
        tok = self.peek()
        if (tok[0] == "id" and tok[1] not in ("id", "ecco_durable", "std") and self.val(1) == "."
                and self.peek(2)[0] == "id" and self.val(3) == "."):
            # `local.f1.f2 = v` / `local.f1.f2[i] = v` - a nested member chain (a struct inside a struct)
            start = self.i
            name = self.take()[1]
            chain = []
            while self.val() == ".":
                self.take(".")
                chain.append(self.take()[1])
                if self.val() == "(":  # a method call is not an lvalue
                    self.i = start
                    return ("expr", "", "")
            parent = f"L[{name!r}]" + "".join(f".{f}" for f in chain[:-1])
            if self.val() == "[":
                self.take("[")
                idx = self.expr()
                self.take("]")
                read = f"{parent}.{chain[-1]}[{idx}]"
                return ("chain_idx", read, read)
            return ("chain", f"{parent}.{chain[-1]}", (parent, chain[-1]))
        return super().lvalue()

    def assign(self, target, rhs):
        kind, _read, w = target
        if kind == "gindex":
            return f"S.g[{w[0]!r}][{w[1]}] = {rhs}"
        if kind == "chain":
            return f"setattr({w[0]}, {w[1]!r}, D.FB_copy({rhs}))"
        if kind == "chain_idx":
            return f"{w} = {rhs}"
        if kind == "local" and w in self.refs:
            return f"L[{w!r}].assign_from({rhs})"
        if kind == "local":
            ctype = self.ltypes.get(w)
            if ctype and parse_array_ctype(ctype):
                return f"L[{w!r}] = {self.wrap_expr(rhs, ctype)}"
        return super().assign(target, rhs)

    # ------------------------------------------------------------- expressions
    def unary(self):
        v = self.val()
        if v == "~":
            self.take()
            return f"(~{self.unary()})"
        if v == "+":
            self.take()
            return self.unary()
        if v in ("++", "--"):
            self.take()
            return self._incdec(self.unary(), 1 if v == "++" else -1, post=False)
        if v == "static_cast":
            self.take("static_cast")
            self.take("<")
            ctype = self._type_phrase_until((">",))
            self.take(">")
            self.take("(")
            operand = self.expr()
            self.take(")")
            return self._cast(ctype, operand)
        if v in ("reinterpret_cast", "const_cast", "dynamic_cast"):
            raise FbbNotModelled(v)
        if v == "(":
            j, words = 1, []
            while self.val(j) in _TYPE_WORDS or self.val(j) in _SCALAR_DECL or self.val(j) == "const":
                if self.val(j) != "const":
                    words.append(self.val(j))
                j += 1
            if words and self.val(j) == ")" and tuple(words) in _CAST_PHRASES:
                ctype = _CAST_PHRASES[tuple(words)]
                for _ in range(j + 1):
                    self.take()
                return self._cast(ctype, self.unary())
            if words and self.val(j) == ")" and words == ["char"]:
                raise FbbNotModelled("(char) cast: the signedness of char is platform-dependent")
        r = super().unary()
        if self.val() in ("++", "--"):
            op = self.take()[1]
            return self._incdec(r, 1 if op == "++" else -1, post=True)
        return r

    @staticmethod
    def _cast(ctype, operand):
        if ctype in ("float", "double"):
            return f"float({operand})"
        return f"cast_t({operand}, {ctype!r})"

    def _incdec(self, code, delta, post):
        m = re.fullmatch(r"(?:U32|U64|CStr)\((.+)\)", code)
        if m:
            code = m.group(1)
        m = re.fullmatch(r"S\.g\[('[^']+')\]", code)
        if m:
            return f"S.incdec_g({m.group(1)}, {delta}, {post})"
        m = re.fullmatch(r"L\[('[^']+')\]", code)
        if m:
            name = eval(m.group(1))  # noqa: S307 - a quoted identifier emitted by this translator
            return f"incdec_l(L, {m.group(1)}, {delta}, {post}, {self.ltypes.get(name)!r})"
        m = re.fullmatch(r"((?:S\.g|L)\[[^\]]+\])\[(.+)\]", code)
        if m:
            return f"incdec_idx({m.group(1)}, {m.group(2)}, {delta}, {post})"
        raise FbbNotModelled(f"++/-- on a non-assignable expression ({code})")

    def primary(self):
        kind, v = self.peek()
        if kind == "id":
            if v == "id" and self.val(1) == "(" and self.val(3) == ")":
                name = self.val(2)
                ct = self.gtypes.get(name)
                if ct in UNSIGNED_CTYPES:
                    for _ in range(4):
                        self.take()
                    return f"{'U64' if UNSIGNED_CTYPES[ct].BITS == 64 else 'U32'}(S.g[{name!r}])"
                if ct == "std::string":
                    for _ in range(4):
                        self.take()
                    return f"CStr(S.g[{name!r}])"
            if v == "millis" and self.val(1) == "(":
                for _ in range(3):
                    self.take()
                return "U32(S.millis())"
            if v == "millis_64" and self.val(1) == "(":
                for _ in range(3):
                    self.take()
                return "U64(S.millis_64())"
            if v == "random_uint32" and self.val(1) == "(":
                for _ in range(3):
                    self.take()
                return "U32(S.random_uint32())"
            if v == "sizeof":
                return self._sizeof()
            if v == "std":
                r = self._std_primary()
                if r is not None:
                    return r
            if v == "static_assert":
                raise FbbNotModelled("static_assert used as an expression")
            if v not in _BASE_PRIMARY_IDS and v not in ("millis", "millis_64", "random_uint32"):
                if v in self.lambdas:
                    return super().primary()
                if v in self.ltypes or v in self.params:
                    self.take()
                    ct = self.ltypes.get(v)
                    cls = UNSIGNED_CTYPES.get(ct)
                    if cls is not None:
                        return f"{'U64' if cls.BITS == 64 else 'U32'}(L[{v!r}])"
                    if ct == "std::string":
                        return f"CStr(L[{v!r}])"
                    return f"L[{v!r}]"
                raise FbbNotModelled(f"undeclared identifier {v!r} (the harness needs every ecco_* name fully qualified; "
                                     "`using namespace`, enums and macros are not modelled)")
        return super().primary()

    def _std_primary(self):
        if self.val(1) != "::":
            return None
        name = self.val(2)
        if name == "to_string":
            for _ in range(3):
                self.take()
            self.take("(")
            e = self.expr()
            self.take(")")
            return f"CStr(c_to_string({e}))"
        if name == "string" and self.val(3) == "::" and self.val(4) == "npos":
            for _ in range(5):
                self.take()
            return "NPOS"
        if name == "string" and self.val(3) == "(":
            for _ in range(3):
                self.take()
            self.take("(")
            args = []
            while self.val() != ")":
                args.append(self.expr())
                if self.val() == ",":
                    self.take(",")
            self.take(")")
            return f"str_from({', '.join(args)})"
        if name == "array" and self.val(3) == "<":
            ctype = self.parse_type()
            arr = parse_array_ctype(ctype)
            if arr is None or self.val() != "{":
                raise FbbNotModelled(f"{ctype} temporary")
            self.take("{")
            args = []
            while self.val() != "}":
                args.append(self.expr())
                if self.val() == ",":
                    self.take(",")
            self.take("}")
            return f"FbArray({arr[0]!r}, {arr[1]}, [{', '.join(args)}])"
        return None

    def _sizeof(self):
        self.take("sizeof")
        paren = self.val() == "("
        if paren:
            self.take("(")
        size = None
        # a type name
        j, words = 0, []
        while self.val(j) in _TYPE_WORDS or self.val(j) in _SCALAR_DECL:
            words.append(self.val(j))
            j += 1
        if words and self.val(j) in (")", None) and tuple(words) in _CAST_PHRASES:
            for _ in range(j):
                self.take()
            size = str(CTYPE_SIZEOF[_CAST_PHRASES[tuple(words)]])
        elif self.val() == "id" and self.val(1) == "(" and self.val(3) == ")" and self.val(2) in self.array_globals:
            elem, n = self.array_globals[self.val(2)]
            for _ in range(4):
                self.take()
            size = str(CTYPE_SIZEOF[elem if elem != "bool" else "bool"] * n)
        elif self.peek(0)[0] == "id" and self.val() in self.char_array_sizes and self.val(1) == ")":
            size = str(self.char_array_sizes[self.take()[1]])
        elif self.peek(0)[0] == "id" and self.val() in self.arrays and self.val(1) == ")":
            name = self.take()[1]
            size = f"(len(L[{name!r}]) * {CTYPE_SIZEOF[self.arrays[name]]})"
        elif self.peek(0)[0] == "id" and self.val() in self.ltypes and CTYPE_SIZEOF.get(self.ltypes[self.val()]) \
                and self.val(1) == ")":
            size = str(CTYPE_SIZEOF[self.ltypes[self.take()[1]]])
        elif self.val() == "ecco_durable" and self.val(1) == "::" and self.peek(2)[0] == "id" and self.val(3) == ")":
            self.take()
            self.take("::")
            size = f"D.sizeof_of({self.take()[1]!r})"
        if size is None:
            raise FbbNotModelled("sizeof of an expression / type the harness does not know the size of")
        if paren:
            self.take(")")
        return f"U32({size})"

    def postfix(self, base):
        # `id(x).state` of a text sensor / switch: strings read back as std::string (FCStr)
        if base.startswith("S.ent(") and self.val() == "." and self.val(1) == "state" and self.val(2) != "(":
            self.take()
            self.take()
            base = f"_S({base}.state)"
        return super().postfix(base)
