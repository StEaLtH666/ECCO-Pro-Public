"""FB-B1 harness primitives - a LEAF module (imports only _dump_sim).

Everything the FB-B1 lambdas need as C++ value types, kept apart from the
simulator so _fbb_harness / _fbb1_xpile / _fbb1_engine / _fbb1_fbcap can all
import it without a cycle:

  FbbNotModelled   something the FB-B harness does not model (never skipped)
  PowerCut         a power cut (DirectNvs cut point, or a timeline event)
  FbbTimeout       a run_until_* bound was exceeded
  FbArray          std::array<T, N> / T[N]: fixed size, C-width wrapping on
                   every store, bounds-checked (negative and out-of-range
                   indexes RAISE - C++ undefined behaviour must never pass),
                   value semantics through copy(), .size() / .data() / .fill()
  U32 / U64        uint32_t / uint64_t VALUES: + - * << ~ wrap at their width
                   and mix with plain ints the way C's usual arithmetic
                   conversions do, so `millis() - id(x) >= K` is wrap-safe
  FCStr            std::string: `+` yields another FCStr, substr / find /
                   compare / length (a CStr, so .c_str() / .size() work)
  ConstArray       a read-only constexpr array (a mirror constant)

FB-B2 additions (self-tested by test_fallback_save_harness.py):
  StringRef        esphome::StringRef, the type of every `string` api-action
                   variable (the generated lambda is
                   `[](StringRef action, StringRef target_id, ...)`). Modelled on
                   esphome/core/string_ref.h: size / length / empty / str() /
                   c_str() / starts_with / compare / find / substr / operator[],
                   `==` `!=` with std::string / const char * / StringRef, `<`
                   between StringRefs, the implicit conversion to std::string
                   (assignment, std::string(x), `+`), and - the point of the
                   class - c_str() is NOT NUL-terminated: it is a CPtr that
                   reads on into the bytes behind the string, exactly like
                   the C++ pointer into the protobuf buffer does
  CPtr             a `const char *` into such a buffer (no members at all:
                   `ptr.size()` is a compile error in C++)
  str_mut          the mutating std::string members (assign / append / clear /
                   push_back / pop_back / erase / resize / insert) as pure
                   functions; the transpiler turns `s.append(x);` into an
                   assignment (Python strings are immutable)
  FCStr.str()      raises FbbNotModelled: std::string has NO str() member (only
                   StringRef does); a lambda that calls it on a std::string does
                   not compile

No I/O, no hardware.
"""

from __future__ import annotations

import copy
import operator
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dump_sim as ds  # noqa: E402


class FbbNotModelled(ds.Unsupported):
    """Something the FB-B harness does not model - never skipped silently."""


class PowerCut(Exception):
    """Raised by DirectNvs at the configured cut point, or by a timeline power-cut event."""


class FbbTimeout(AssertionError):
    """A run_until_* / run_until_idle bound was exceeded."""


# ---------------------------------------------------------------------------
# C types
# ---------------------------------------------------------------------------
# (bits, signed) for every integer type an array element / cast may name.
_INT_TYPES = {
    "uint8_t": (8, False), "uint16_t": (16, False), "uint32_t": (32, False), "uint64_t": (64, False),
    "int8_t": (8, True), "int16_t": (16, True), "int32_t": (32, True), "int64_t": (64, True),
    "int": (32, True), "unsigned": (32, False), "unsigned int": (32, False), "size_t": (32, False),
    "long": (32, True), "unsigned long": (32, False), "long long": (64, True), "unsigned long long": (64, False),
}
ARRAY_ELEM_TYPES = frozenset({"uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t", "int16_t", "int32_t", "int64_t",
                              "int", "bool"})
# sizeof() of the scalar types the FB code may name (ESP32 / xtensa: int = long = pointer = 4 bytes).
CTYPE_SIZEOF = {"uint8_t": 1, "int8_t": 1, "bool": 1, "char": 1, "uint16_t": 2, "int16_t": 2, "uint32_t": 4,
                "int32_t": 4, "int": 4, "unsigned": 4, "unsigned int": 4, "size_t": 4, "long": 4, "unsigned long": 4,
                "uint64_t": 8, "int64_t": 8, "long long": 8, "unsigned long long": 8, "float": 4, "double": 8}


_DURATION = re.compile(r"^\s*(\d+)\s*(ms|s|min)?\s*$")


def duration_ms(v) -> int:
    """An ESPHome duration (`250ms`, `10s`, `5min`, or a bare number of ms) in ms."""
    if isinstance(v, (int, float)):
        return int(v)
    m = _DURATION.match(str(v))
    if not m:
        raise FbbNotModelled(f"duration {v!r}")
    n, unit = int(m.group(1)), m.group(2) or "ms"
    return n * {"ms": 1, "s": 1000, "min": 60000}[unit]


def cwrap(value, ctype):
    """ds.wrap() extended to int8/int16/int64 and strict about unknown types
    (ds.wrap silently returns its argument for a type it does not know)."""
    if ctype is None:
        return value
    if ctype == "bool":
        return bool(value)
    if ctype in ("float", "double"):
        return float(value)
    spec = _INT_TYPES.get(ctype)
    if spec is None:
        raise FbbNotModelled(f"cast / store to C type {ctype!r} is not modelled")
    bits, signed = spec
    if isinstance(value, float):
        if value != value:
            raise FbbNotModelled("NaN converted to an integer")
        value = int(value)  # C truncation toward zero
    value = int(value) & ((1 << bits) - 1)
    if signed and value >= 1 << (bits - 1):
        value -= 1 << bits
    return value


# ---------------------------------------------------------------------------
# Unsigned values: uint32_t / uint64_t with C arithmetic
# ---------------------------------------------------------------------------
class _UInt(int):
    """An unsigned integer VALUE. Arithmetic with another _UInt takes the
    wider type; with a plain int the operand is converted modulo 2^bits (C's
    usual arithmetic conversions: unsigned wins), so `(uint32_t)` wrap-around
    needs no explicit cast. Division / modulo go through c_div_t / c_mod_t."""

    BITS = 32
    MASK = (1 << 32) - 1

    def __new__(cls, value=0):
        if isinstance(value, float):
            if value != value:
                raise FbbNotModelled("NaN converted to an unsigned integer")
            value = int(value)
        return int.__new__(cls, int(value) & cls.MASK)

    def __repr__(self):
        return f"{type(self).__name__}({int(self)})"

    def _other(self, other):
        """(class, other as int) for a binary operation, or None."""
        if isinstance(other, _UInt):
            return (type(other) if other.BITS > self.BITS else type(self)), int(other)
        if isinstance(other, int):
            return type(self), int(other)
        return None


def _mk_arith(fn, reflected=False):
    def op(self, other):
        r = self._other(other)
        if r is None:
            if isinstance(other, float):
                return fn(other, float(self)) if reflected else fn(float(self), other)
            return NotImplemented
        cls, o = r
        return cls(fn(o, int(self)) if reflected else fn(int(self), o))
    return op


def _mk_cmp(fn):
    def cmp(self, other):
        if isinstance(other, float):
            return fn(float(self), other)
        if not isinstance(other, int):
            return NotImplemented
        o = int(other)
        if not isinstance(other, _UInt) and o < 0:
            o &= self.MASK  # C converts the signed operand to unsigned
        return fn(int(self), o)
    return cmp


for _name, _fn in (("add", operator.add), ("sub", operator.sub), ("mul", operator.mul), ("lshift", operator.lshift),
                   ("rshift", operator.rshift), ("and", operator.and_), ("or", operator.or_), ("xor", operator.xor)):
    setattr(_UInt, f"__{_name}__", _mk_arith(_fn))
    setattr(_UInt, f"__r{_name}__", _mk_arith(_fn, reflected=True))
for _name, _fn in (("lt", operator.lt), ("le", operator.le), ("gt", operator.gt), ("ge", operator.ge),
                   ("eq", operator.eq), ("ne", operator.ne)):
    setattr(_UInt, f"__{_name}__", _mk_cmp(_fn))
_UInt.__hash__ = int.__hash__
_UInt.__neg__ = lambda self: type(self)(-int(self))
_UInt.__pos__ = lambda self: self
_UInt.__invert__ = lambda self: type(self)(~int(self))


class U32(_UInt):
    BITS = 32
    MASK = (1 << 32) - 1


class U64(_UInt):
    BITS = 64
    MASK = (1 << 64) - 1


UNSIGNED_CTYPES = {"uint32_t": U32, "unsigned": U32, "unsigned int": U32, "size_t": U32, "unsigned long": U32,
                   "uint64_t": U64, "unsigned long long": U64}


def c_div_t(a, b):
    """C division; unsigned operands divide as unsigned of the wider type."""
    if isinstance(a, _UInt) or isinstance(b, _UInt):
        cls = U64 if (isinstance(a, U64) or isinstance(b, U64)) else U32
        return cls((int(a) & cls.MASK) // (int(b) & cls.MASK))
    return ds.c_div(a, b)


def c_mod_t(a, b):
    if isinstance(a, _UInt) or isinstance(b, _UInt):
        cls = U64 if (isinstance(a, U64) or isinstance(b, U64)) else U32
        return cls((int(a) & cls.MASK) % (int(b) & cls.MASK))
    return ds.c_mod(a, b)


def cast_t(value, ctype):
    """A C cast `(ctype) value`: unsigned 32/64-bit types stay typed so later
    arithmetic wraps; everything else is a plain wrapped int."""
    cls = UNSIGNED_CTYPES.get(ctype)
    if cls is not None:
        return cls(value)
    return cwrap(value, ctype)


# ---------------------------------------------------------------------------
# std::string
# ---------------------------------------------------------------------------
class FCStr(ds.CStr):
    """std::string for lambda code: concatenation keeps the type (so
    `(a + b).c_str()` works), plus the few members FB code may use."""

    def __add__(self, other):
        if isinstance(other, str):
            return FCStr(str.__add__(self, other))
        return NotImplemented

    def __radd__(self, other):
        if isinstance(other, str):
            return FCStr(str.__add__(other, self))
        return NotImplemented

    def length(self):
        return len(self)

    def substr(self, pos=0, count=None):
        pos = int(pos)
        if pos > len(self):
            raise FbbNotModelled("std::string::substr: position past the end (C++ throws out_of_range)")
        end = len(self) if count is None or int(count) >= len(self) - pos else pos + int(count)
        return FCStr(str.__getitem__(self, slice(pos, end)))

    def find(self, needle, pos=0):
        i = str.find(self, str(needle), int(pos))
        return NPOS if i < 0 else i

    def compare(self, other):
        a, b = str(self), str(other)
        return (a > b) - (a < b)

    def at(self, i):
        i = int(i)
        if not 0 <= i < len(self):
            raise FbbNotModelled(f"std::string::at({i}) out of range (C++ throws)")
        return str.__getitem__(self, i)

    # FB-B2 ---------------------------------------------------------------------------------------------------
    def str(self):
        raise FbbNotModelled("std::string has no str() member - only esphome::StringRef (an api-action variable) has; "
                             "a lambda that calls it on a std::string does not compile")

    def data(self):
        return self

    def front(self):
        if not len(self):
            raise FbbNotModelled("std::string::front() of an empty string (undefined behaviour)")
        return FCStr(str.__getitem__(self, 0))

    def back(self):
        if not len(self):
            raise FbbNotModelled("std::string::back() of an empty string (undefined behaviour)")
        return FCStr(str.__getitem__(self, len(self) - 1))

    def rfind(self, needle, pos=None):
        end = len(self) if pos is None or int(pos) >= len(self) else int(pos) + len(str(needle))
        i = str.rfind(self, str(needle), 0, end)
        return NPOS if i < 0 else i

    def starts_with(self, prefix):
        return str.startswith(self, str(prefix))

    def ends_with(self, suffix):
        return str.endswith(self, str(suffix))


NPOS = U32(0xFFFFFFFF)  # std::string::npos (size_t is 32-bit on the ESP32)


# ---------------------------------------------------------------------------
# esphome::StringRef - the type of an api-action `string` variable
# ---------------------------------------------------------------------------
# What stands behind the characters of a StringRef: the generated api code points it into the protobuf message buffer,
# so the bytes after the string are the NEXT field (never a NUL it can rely on). Any marker text that is not "" works;
# a test that wants a different neighbour passes `tail=` to call_api().
STRINGREF_TAIL = "<next-protobuf-field>"


class CPtr(str):
    """A `const char *` into a buffer that is NOT NUL-terminated at the end of a StringRef: reading it as a C string
    (std::string(ptr), snprintf("%s", ptr), strlen, ==) runs on into the bytes behind the string - the value of this
    str IS that over-read text. A pointer has no members: `ptr.size()` is a compile error in C++, so every
    non-dunder attribute raises FbbNotModelled."""

    __slots__ = ()

    def __getattribute__(self, name):
        if name.startswith("__") and name.endswith("__"):
            return str.__getattribute__(self, name)
        raise FbbNotModelled(f"`const char *` has no member {name!r} (a StringRef::c_str() pointer is not a std::string)")


def _text_of(v, what: str) -> str:
    """The characters of a std::string / const char * / StringRef argument (a CPtr reads on past the string: that IS
    its text)."""
    if isinstance(v, (StringRef, str)):
        return str(v)
    if callable(getattr(v, "c_str", None)):  # a header TextBuf (the Python mirror's text builders)
        return str(v.c_str())
    raise FbbNotModelled(f"{what}: {type(v).__name__} is not a string / StringRef")


class StringRef:
    """esphome::StringRef (esphome/core/string_ref.h, ESPHome 2026.8.2) for a lambda parameter. `value` is the
    string; `tail` the bytes behind it in the buffer (see STRINGREF_TAIL)."""

    __slots__ = ("_v", "_tail")

    def __init__(self, value="", tail=STRINGREF_TAIL):
        if isinstance(value, StringRef):
            value = value._v
        object.__setattr__(self, "_v", str(value))
        object.__setattr__(self, "_tail", str(tail))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise FbbNotModelled(f"esphome::StringRef has no member {name!r} in the FB-B harness model (modelled: size, length, "
                             "empty, str, c_str, starts_with, compare, find, substr, operator[], ==, !=, <, +)")

    def __setattr__(self, name, value):
        raise FbbNotModelled("a StringRef is an immutable view")

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    # members --------------------------------------------------------------------------------------------------
    def c_str(self):
        return CPtr(self._v + self._tail)

    def size(self):
        return len(self._v)

    length = size

    def empty(self):
        return len(self._v) == 0

    def str(self):
        return FCStr(self._v)

    def starts_with(self, prefix):
        return self._v.startswith(_text_of(prefix, "StringRef::starts_with"))

    def compare(self, other):
        a, b = self._v, _text_of(other, "StringRef::compare")
        return (a > b) - (a < b)

    def find(self, needle, pos=0):
        """find(const char *s, pos): strstr over the NUL-terminated text (so it READS ON past the end of the view), then
        the match must lie inside the view; find(char, pos) is memchr over the view (same result for one character)."""
        pos = int(pos)
        s = _text_of(needle, "StringRef::find")
        if pos >= len(self._v):
            return NPOS
        i = (self._v + self._tail).find(s, pos)
        return NPOS if i < 0 or i + len(s) > len(self._v) else i

    def substr(self, pos=0, count=NPOS):
        pos = int(pos)
        if pos >= len(self._v):
            return FCStr("")
        n = len(self._v) - pos if int(count) == int(NPOS) or pos + int(count) > len(self._v) else int(count)
        return FCStr(self._v[pos:pos + n])

    def __getitem__(self, i):
        i = int(i)
        if not 0 <= i < len(self._v):
            raise FbbNotModelled(f"StringRef::operator[]({i}) out of range 0..{len(self._v) - 1} (undefined behaviour)")
        return FCStr(self._v[i])

    # operators ------------------------------------------------------------------------------------------------
    def __str__(self):  # the implicit operator std::string()
        return self._v

    def __eq__(self, other):
        if isinstance(other, (StringRef, str)):
            return self._v == str(other)
        return NotImplemented

    def __ne__(self, other):
        r = self.__eq__(other)
        return r if r is NotImplemented else not r

    def __lt__(self, other):
        if isinstance(other, StringRef):
            return self._v < other._v
        raise FbbNotModelled("operator< is defined only between two StringRefs")

    __hash__ = None

    def __add__(self, other):  # operator+(StringRef, const char *) / (StringRef, std::string) -> std::string
        if isinstance(other, StringRef):
            raise FbbNotModelled("StringRef + StringRef is ambiguous (does not compile)")
        if isinstance(other, str):
            return FCStr(self._v + str(other))
        return NotImplemented

    def __radd__(self, other):  # operator+(const char *, StringRef) / (std::string, StringRef)
        if isinstance(other, StringRef):
            raise FbbNotModelled("StringRef + StringRef is ambiguous (does not compile)")
        if isinstance(other, str):
            return FCStr(str(other) + self._v)
        return NotImplemented

    def __bool__(self):
        raise FbbNotModelled("a StringRef has no operator bool (use empty())")

    def __repr__(self):
        return f"StringRef({self._v!r})"


# ---------------------------------------------------------------------------
# std::string construction from pointers / counts
# ---------------------------------------------------------------------------
def str_from(*args):
    """std::string(...) with 0 / 1 / 2 arguments: (), (const std::string& | const char * | StringRef), (ptr, n) = the first n
    characters of the pointer's text (so `std::string(ref.c_str(), ref.size())` is exactly the view, and `std::string(ref.c_str())`
    reads on past it), and (count, char)."""
    if not args:
        return FCStr("")
    if len(args) == 1:
        return FCStr(_text_of(args[0], "std::string(...)"))
    if len(args) == 2:
        if isinstance(args[0], int) and not isinstance(args[0], bool):
            return FCStr(str(args[1]) * int(args[0]))
        t, n = _text_of(args[0], "std::string(ptr, n)"), int(args[1])
        if n > len(t):
            raise FbbNotModelled(f"std::string(ptr, {n}): the pointer's text has only {len(t)} characters")
        return FCStr(t[:n])
    raise FbbNotModelled(f"std::string constructed from {len(args)} arguments")


# ---------------------------------------------------------------------------
# std::string mutators
# ---------------------------------------------------------------------------
def str_mut(op, cur, *args):
    """The new value of std::string `cur` after `cur.<op>(*args)` (assign / append / clear / push_back / pop_back / erase /
    resize / insert) - the transpiler assigns it back (Python strings are immutable). A `(ptr, n)` pair takes the first n
    characters of the pointer's text (so a StringRef::c_str() with its size() gives exactly the view; with a wrong size
    or no size at all it reads on past the end, like C++)."""
    s = str(cur)

    def chars(a, n=None):
        t = _text_of(a, f"std::string::{op}")
        if n is None:
            return t
        n = int(n)
        if n > len(t):
            raise FbbNotModelled(f"std::string::{op}(ptr, {n}): the pointer's text has only {len(t)} characters")
        return t[:n]

    if op in ("assign", "append"):
        if len(args) == 1:
            piece = chars(args[0])
        elif len(args) == 2 and isinstance(args[0], int) and not isinstance(args[0], bool):
            piece = str(args[1]) * int(args[0])  # (count, char)
        elif len(args) == 2:
            piece = chars(args[0], args[1])
        else:
            raise FbbNotModelled(f"std::string::{op} with {len(args)} arguments is not modelled")
        return FCStr(piece if op == "assign" else s + piece)
    if op in ("reserve", "shrink_to_fit"):  # capacity only: no observable effect on the value
        return FCStr(s)
    if op in ("replace", "swap"):
        raise FbbNotModelled(f"std::string::{op}() is not modelled")
    if op == "clear" and not args:
        return FCStr("")
    if op == "push_back" and len(args) == 1:
        return FCStr(s + chars(args[0]))
    if op == "pop_back" and not args:
        if not s:
            raise FbbNotModelled("std::string::pop_back() of an empty string (undefined behaviour)")
        return FCStr(s[:-1])
    if op == "erase":
        pos = int(args[0]) if args else 0
        if pos > len(s):
            raise FbbNotModelled("std::string::erase: position past the end (C++ throws out_of_range)")
        count = int(args[1]) if len(args) > 1 else int(NPOS)
        end = len(s) if count >= len(s) - pos else pos + count
        return FCStr(s[:pos] + s[end:])
    if op == "resize" and 1 <= len(args) <= 2:
        n = int(args[0])
        fill = str(args[1]) if len(args) == 2 else "\0"
        return FCStr(s[:n] if n <= len(s) else s + fill * (n - len(s)))
    if op == "insert" and len(args) == 2:
        pos = int(args[0])
        if pos > len(s):
            raise FbbNotModelled("std::string::insert: position past the end (C++ throws out_of_range)")
        return FCStr(s[:pos] + chars(args[1]) + s[pos:])
    raise FbbNotModelled(f"std::string::{op}({len(args)} argument(s)) is not modelled")


# ---------------------------------------------------------------------------
# Arrays
# ---------------------------------------------------------------------------
def _index(i, size):
    if isinstance(i, slice):
        raise FbbNotModelled("slice indexing is not a C++ operation")
    try:
        i = operator.index(i)
    except TypeError as e:
        raise FbbNotModelled(f"array index {i!r} is not an integer") from e
    if i < 0 or i >= size:
        raise FbbNotModelled(f"array index {i} out of range 0..{size - 1} (undefined behaviour in C++)")
    return i


def _no_resize(*_a, **_k):
    raise FbbNotModelled("a std::array has a fixed size")


class FbArray(list):
    """std::array<T, N> / T name[N]. `ctype` None = no element wrapping.

    Lambda code (the transpiled C++) gets STRICT access: negative / out-of-range indexes and slices raise. The Python
    mirror of a header function, on the other hand, is ordinary Python (`words[1:7] = v[15:21]`, `words[-1]`): the
    adapter wraps every call in `lenient(...)`, under which Python indexing and same-length slice assignment work
    (elements are still wrapped to the C width and the size can never change)."""

    _lenient = 0

    def __init__(self, ctype, size, init=None):
        if ctype is not None and ctype not in ARRAY_ELEM_TYPES:
            raise FbbNotModelled(f"array element type {ctype!r} is not modelled")
        list.__init__(self, [False if ctype == "bool" else 0] * int(size))
        self.ctype = ctype
        if init is not None:
            init = list(init)
            if len(init) > len(self):
                raise FbbNotModelled(f"{len(init)} initialisers for an array of {len(self)} (C++: too many initializers)")
            for i, v in enumerate(init):
                self[i] = v

    # element access (strict for lambda code, Pythonic for the mirror - see the class docstring)
    def __getitem__(self, i):
        if self._lenient:
            return list.__getitem__(self, i)
        return list.__getitem__(self, _index(i, len(self)))

    def __setitem__(self, i, v):
        if self._lenient:
            if isinstance(i, slice):
                idxs = range(*i.indices(len(self)))
                vals = list(v)
                if len(vals) != len(idxs):
                    raise FbbNotModelled(f"a std::array has a fixed size: slice assignment of {len(vals)} elements into "
                                         f"{len(idxs)}")
                for j, x in zip(idxs, vals):
                    list.__setitem__(self, j, cwrap(x, self.ctype))
                return
            list.__setitem__(self, i, cwrap(v, self.ctype))
            return
        list.__setitem__(self, _index(i, len(self)), cwrap(v, self.ctype))

    # std::array members
    def size(self):
        return len(self)

    def empty(self):
        return len(self) == 0

    def data(self):
        return self

    def at(self, i):
        return self[i]

    def front(self):
        return self[0]

    def back(self):
        return self[len(self) - 1]

    def fill(self, v):
        for i in range(len(self)):
            self[i] = v

    def assign_from(self, other):
        other = list(other)
        if len(other) != len(self):
            raise FbbNotModelled(f"assignment of {len(other)} elements to an array of {len(self)}")
        for i, v in enumerate(other):
            self[i] = v

    def copy(self):
        return FbArray(self.ctype, len(self), list(self))

    __copy__ = copy

    def __deepcopy__(self, memo):
        return self.copy()

    def to_bytes(self):
        if self.ctype != "uint8_t":
            raise FbbNotModelled("to_bytes() is only defined for uint8_t arrays")
        return bytes(list(self))

    @classmethod
    def from_bytes(cls, data):
        data = bytes(data)
        return cls("uint8_t", len(data), list(data))

    # a fixed-size container: no structural changes
    append = extend = insert = pop = remove = clear = sort = reverse = _no_resize
    __delitem__ = __iadd__ = __imul__ = _no_resize

    def __repr__(self):
        return f"FbArray<{self.ctype}>({list.__repr__(self)})"


class lenient:
    """`with lenient(arrays): ...` - Pythonic indexing on these FbArrays for the duration (re-entrant)."""

    def __init__(self, arrays):
        self.arrays = list(arrays)

    def __enter__(self):
        for a in self.arrays:
            a._lenient += 1
        return self

    def __exit__(self, *exc):
        for a in self.arrays:
            a._lenient -= 1
        return False


class ConstArray(list):
    """A constexpr array constant of a mirror module (REGS, ...): read-only,
    bounds-checked, with the std::array members."""

    def __init__(self, items):
        list.__init__(self, items)

    def __getitem__(self, i):
        return list.__getitem__(self, _index(i, len(self)))

    def __setitem__(self, i, v):
        raise FbbNotModelled("assignment to a constexpr array constant")

    def size(self):
        return len(self)

    def empty(self):
        return len(self) == 0

    def data(self):
        return self

    def at(self, i):
        return self[i]

    def copy(self):
        return ConstArray(list(self))

    __copy__ = copy

    def __deepcopy__(self, memo):
        return self.copy()

    append = extend = insert = pop = remove = clear = sort = reverse = _no_resize
    __delitem__ = __iadd__ = __imul__ = _no_resize


def mkarr(ctype, size, value):
    """A copy of `value` as FbArray<ctype>[size] (the C++ array assignment /
    initialisation from another array or a function result)."""
    if isinstance(value, (list, tuple)) and len(value) == size:
        return FbArray(ctype, size, list(value))
    raise FbbNotModelled(f"cannot initialise std::array<{ctype}, {size}> from "
                         f"{type(value).__name__}{'' if not isinstance(value, (list, tuple)) else f' of {len(value)}'}")


def parse_array_ctype(ctype: str):
    """'std::array<uint16_t, 31>' -> ('uint16_t', 31); None for anything else."""
    m = re.fullmatch(r"std::array<\s*([A-Za-z_][\w ]*?)\s*,\s*(\d+)\s*>", ctype)
    if not m or m.group(1) not in ARRAY_ELEM_TYPES:
        return None
    return m.group(1), int(m.group(2))


def deep_copy(value):
    """C++ value semantics for anything that may be assigned / passed by value."""
    return copy.deepcopy(value)
