"""The generic `ecco_fbcap::` namespace adapter for the strict FB-B simulator.

H's pure header firmware/include/ecco_fallback_capture.h has a Python mirror,
registry/fallback_capture.py, with the SAME names (snake_case / CamelCase).
This adapter exposes that mirror to transpiled lambdas BY INTROSPECTION, so no
harness change is needed when H adds, renames or removes a name:

    ecco_fbcap::CANDIDATE_TTL_MS            a constant      -> int / FCStr / ConstArray
    ecco_fbcap::Purpose::REVIEW             an enum member  -> int
    ecco_fbcap::capture_refusals(pod, w)    a function      -> called with converted arguments
    ecco_fbcap::SomePod pod{};              a type          -> PodValue (dataclass / namedtuple / class)
    ecco_fbcap::CaptureWords w{};           an alias        -> FbArray<uint16_t>[31] (see HARNESS_TYPES)

Conventions the mirror needs to follow (all optional; defaults in brackets):
  * POD structs are dataclasses (or namedtuples); a field's C width comes from
    `dataclasses.field(metadata={"ctype": "uint16_t"})`, a string annotation
    naming a C type, or a class attribute `CTYPES = {"field": "uint16_t"}`.
    [No width known: stores are not wrapped.]
  * std::array fields / parameters / returns are Python lists. An argument
    handed to a function is the LIVE FbArray (a list subclass), so a function
    that fills an output buffer in place (`store_block_241(words, values)`)
    just mutates it, exactly like the C++ reference parameter.
    A functional mirror may instead return `(result, new_arg, ...)` and list the
    out-parameters in `HARNESS_OUT_PARAMS = {"fname": (argindex, ...)}`; the
    adapter then writes the new values back into those arguments.
  * Text functions return `str` (-> std::string) or an object with `c_str()`
    (a TextBuf-like; passed through untouched so `.c_str()` / `.size()` work).
  * `HARNESS_TYPES = {"Name": ("array", "uint16_t", 31)}` declares array
    aliases; CaptureWords is known by default.
  * `HARNESS_SIZEOF = {"Name": 8}` answers `sizeof(ecco_fbcap::Name)`.

A name the mirror does not define raises FbbNotModelled naming it - never a
silent default.

FB-B2: the SAME class serves `ecco_fbsave::` (firmware/include/ecco_fallback_save.h and its
Python mirror registry/fallback_save.py): FbbSim builds a second FbcapNamespace with
`default_module="fallback_save", ns="ecco_fbsave"`. The mirror module is imported LAZILY, on
the first lookup, so a firmware that never names `ecco_fbsave::` (every FB-B1 suite) needs no
mirror, and a missing mirror raises FbbNotModelled when - and only when - a lambda names it.
"""

from __future__ import annotations

import copy
import dataclasses
import enum
import importlib
import inspect
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _dump_sim as ds  # noqa: E402
from _fbb1_types import (ARRAY_ELEM_TYPES, ConstArray, FbArray, FbbNotModelled, FCStr, _INT_TYPES, _UInt, StringRef,  # noqa: E402
                         cwrap, lenient)

_RECORD_FROM_DICT = None  # set by _fbb_harness: a profile / provision / failback dict -> its FbRecord (or None)


def set_record_factory(fn) -> None:
    global _RECORD_FROM_DICT
    _RECORD_FROM_DICT = fn

DEFAULT_HARNESS_TYPES = {"CaptureWords": ("array", "uint16_t", 31)}


def _is_namedtuple_cls(cls) -> bool:
    return isinstance(cls, type) and issubclass(cls, tuple) and hasattr(cls, "_fields")


def _is_pod_like(obj) -> bool:
    return dataclasses.is_dataclass(obj) and not isinstance(obj, type) or (isinstance(obj, tuple) and hasattr(obj, "_fields"))


def _ctypes_of(cls) -> dict:
    out = {}
    explicit = getattr(cls, "CTYPES", None)
    if isinstance(explicit, dict):
        out.update(explicit)
    if dataclasses.is_dataclass(cls):
        for f in dataclasses.fields(cls):
            if f.name in out:
                continue
            ct = f.metadata.get("ctype") if f.metadata else None
            # a bare Python annotation (`int`, `unsigned`, ...) is NOT a C type: only the fixed-width names (uint8_t ... int64_t)
            # are width hints (a mirror that wants a C `int` / `size_t` says so in CTYPES / the field metadata). Treating `x: int`
            # as C int truncated every uint64_t field (a candidate id, a binding) to 32 bits.
            if ct is None and isinstance(f.type, str) and f.type in _INT_TYPES and f.type.endswith("_t"):
                ct = f.type
            if ct is not None:
                out[f.name] = ct
    return out


def _zero_for(f):
    if f.default is not dataclasses.MISSING:
        return copy.deepcopy(f.default)
    if f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
        return f.default_factory()  # type: ignore[misc]
    t = f.type
    name = t if isinstance(t, str) else getattr(t, "__name__", str(t))
    if name == "bool":
        return False
    if name == "str":
        return ""
    if name.startswith(("list", "List", "tuple", "Tuple", "Sequence")):
        return []
    return 0


def to_py_arg(a):
    """A lambda value -> what the Python mirror function receives. A std::string stays a CStr (a `str` that also
    answers c_str() / size(), like the mirror's own TextBuf); records / arrays are passed live."""
    if isinstance(a, PodValue):
        return a._obj
    if isinstance(a, _UInt):
        return int(a)
    if isinstance(a, StringRef):  # C++ converts a StringRef to a `const std::string &` parameter implicitly
        return FCStr(a.str())
    return a


def arrays_in(values, depth=3):
    """Every FbArray reachable from these call arguments (directly or as a field of a struct argument)."""
    found, stack = [], [(v, depth) for v in values]
    while stack:
        v, d = stack.pop()
        if isinstance(v, PodValue):
            v = v._obj
        if isinstance(v, FbArray):
            found.append(v)
        elif d > 0 and (dataclasses.is_dataclass(v) and not isinstance(v, type)):
            stack.extend((getattr(v, f.name), d - 1) for f in dataclasses.fields(v))
        elif d > 0 and isinstance(v, tuple) and hasattr(v, "_fields"):
            stack.extend((x, d - 1) for x in v)
    return found


def from_py_result(r):
    """A mirror function's return value -> a lambda value."""
    if r is None or isinstance(r, (bool, int, float)):
        return r
    if isinstance(r, str):
        return FCStr(r)
    if isinstance(r, (bytes, bytearray)):
        return FbArray.from_bytes(r)
    if isinstance(r, dict):
        rec = _RECORD_FROM_DICT(r) if _RECORD_FROM_DICT is not None else None
        if rec is None:
            raise FbbNotModelled("a mirror function returned a dict that is not a FallbackProfileV1 / FailbackProvisionV1 / "
                                 "FailbackStateV1 record")
        return rec
    if _is_pod_like(r):
        return PodValue(copy.deepcopy(r), None)
    if isinstance(r, (list, tuple)):
        if all(isinstance(x, (bool, int)) for x in r):
            return ds.Vec(r)
        raise FbbNotModelled("a mirror function returned a list of non-integers")
    if hasattr(r, "c_str"):
        return r
    raise FbbNotModelled(f"a mirror function returned an unsupported {type(r).__name__}")


class PodValue:
    """A header POD struct (dataclass / namedtuple / small class) as a lambda
    local: validated field access, C-width stores, value semantics via copy()."""

    def __init__(self, obj, ptype):
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_ptype", ptype)
        object.__setattr__(self, "_ctypes", _ctypes_of(type(obj)))
        self._normalise()

    # -- internals --------------------------------------------------------
    def _names(self):
        o = self._obj
        if dataclasses.is_dataclass(o):
            return [f.name for f in dataclasses.fields(o)]
        if isinstance(o, tuple) and hasattr(o, "_fields"):
            return list(o._fields)
        return [k for k in vars(o) if not k.startswith("_")]

    def _raw_set(self, name, value):
        o = self._obj
        if isinstance(o, tuple):
            object.__setattr__(self, "_obj", o._replace(**{name: value}))
        else:
            object.__setattr__(o, name, value)

    def _normalise(self):
        """list / tuple fields become bounds-checked FbArrays (in place)."""
        for name in self._names():
            v = getattr(self._obj, name)
            if isinstance(v, (list, tuple)) and not isinstance(v, FbArray) and not hasattr(v, "_fields"):
                ct = self._ctypes.get(name)
                if ct is not None and ct not in ARRAY_ELEM_TYPES:
                    raise FbbNotModelled(f"{type(self._obj).__name__}.{name}: array element type {ct!r} is not modelled")
                self._raw_set(name, FbArray(ct, len(v), list(v)))

    def _convert_store(self, name, value):
        value = to_py_arg(value) if not isinstance(value, (FbArray, list, tuple)) else value
        cur = getattr(self._obj, name)
        if hasattr(value, "as_dict") and hasattr(value, "copy"):
            # a harness record (value semantics: stored as a copy): a field the mirror declares as a `dict` gets the
            # record's dict image, any other field the record object itself
            return value.as_dict() if isinstance(cur, dict) else value.copy()
        if isinstance(cur, (bytes, bytearray)) and isinstance(value, (FbArray, list, tuple)):
            return bytes(list(value))  # a `bytes` field holds the byte image of a std::array<uint8_t, N>
        if isinstance(cur, FbArray):
            if not isinstance(value, (list, tuple)) or len(value) != len(cur):
                raise FbbNotModelled(f"{type(self._obj).__name__}.{name} needs {len(cur)} values")
            new = cur.copy()
            new.assign_from(value)
            return new
        if isinstance(value, (list, tuple)):
            raise FbbNotModelled(f"{type(self._obj).__name__}.{name} is not an array")
        ct = self._ctypes.get(name)
        if ct is not None and isinstance(value, (int, float)):
            return cwrap(value, ct)
        return value

    # -- the C++ surface ----------------------------------------------------
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._names():
            v = getattr(self._obj, name)
            if isinstance(v, str):
                return FCStr(v)
            if _is_pod_like(v):
                return PodValue(v, None)
            if isinstance(v, dict) and _RECORD_FROM_DICT is not None:
                # a field the mirror holds as a record dict (Plan.p_new / .w_new: the C++ struct members) reads as the harness
                # record a lambda hands to the writer (`commit_transition_t(nvs, plan.w_new, ...)`): a COPY, like a C++ value
                rec = _RECORD_FROM_DICT(v)
                if rec is not None:
                    return rec
            return v
        attr = getattr(type(self._obj), name, None)
        if callable(attr):
            bound = getattr(self._obj, name)

            def call(*args):
                with lenient(arrays_in(args)):
                    return from_py_result(bound(*[to_py_arg(a) for a in args]))
            return call
        raise FbbNotModelled(f"ecco_fbcap {type(self._obj).__name__} has no member {name!r}")

    def __setattr__(self, name, value):
        if name not in self._names():
            raise FbbNotModelled(f"ecco_fbcap {type(self._obj).__name__} has no field {name!r}")
        self._raw_set(name, self._convert_store(name, value))

    def set_field(self, name, value):
        setattr(self, name, value)

    def set_elem(self, name, idx, value):
        if name not in self._names():
            raise FbbNotModelled(f"ecco_fbcap {type(self._obj).__name__} has no field {name!r}")
        arr = getattr(self._obj, name)
        if not isinstance(arr, FbArray):
            raise FbbNotModelled(f"{type(self._obj).__name__}.{name} is not an array")
        arr[idx] = to_py_arg(value)

    def copy(self):
        return PodValue(copy.deepcopy(self._obj), self._ptype)

    def assign_from(self, other):
        if not isinstance(other, PodValue) or type(other._obj) is not type(self._obj):
            raise FbbNotModelled("assignment between different struct types")
        for name in self._names():
            self._raw_set(name, copy.deepcopy(getattr(other._obj, name)))

    def as_dict(self):
        out = {}
        for n in self._names():
            v = getattr(self._obj, n)
            out[n] = list(v) if isinstance(v, list) else v
        return out

    def __repr__(self):
        return f"PodValue({self._obj!r})"


class PodType:
    """`ecco_fbcap::SomePod` used as a type: calling it brace-initialises a value."""

    def __init__(self, qual, cls):
        self.qual, self.cls = qual, cls

    def __call__(self, *init):
        cls = self.cls
        if issubclass(cls, str):  # a TextBuf(str)
            return FCStr(cls(*[str(a) for a in init]))
        if dataclasses.is_dataclass(cls):
            fields = dataclasses.fields(cls)
            if len(init) > len(fields):
                raise FbbNotModelled(f"{self.qual}: {len(init)} initialisers for {len(fields)} fields")
            kwargs = {}
            for i, f in enumerate(fields):
                kwargs[f.name] = to_py_arg(init[i]) if i < len(init) else _zero_for(f)
            pod = PodValue(cls(**kwargs), self)
            # route brace-init values through the same width wrapping as later stores
            for i in range(len(init)):
                setattr(pod, fields[i].name, init[i])
            return pod
        if _is_namedtuple_cls(cls):
            if len(init) > len(cls._fields):
                raise FbbNotModelled(f"{self.qual}: too many initialisers")
            return PodValue(cls(*([to_py_arg(a) for a in init] + [0] * (len(cls._fields) - len(init)))), self)
        return PodValue(cls(*[to_py_arg(a) for a in init]), self)


class EnumType:
    """An enum class used as a type: `ecco_fbcap::Kind k = ecco_fbcap::Kind::X;`."""

    def __init__(self, qual, cls):
        self.qual, self.cls = qual, cls

    def __call__(self, *init):
        return int(init[0]) if init else 0


class ArrayType:
    """An array alias (CaptureWords)."""

    def __init__(self, qual, ctype, size):
        self.qual, self.ctype, self.size = qual, ctype, size

    def __call__(self, *init):
        return FbArray(self.ctype, self.size, [to_py_arg(a) for a in init] if init else None)


class AdapterFn:
    def __init__(self, ns, qual, name, fn):
        self.ns, self.qual, self.name, self.fn = ns, qual, name, fn

    def __call__(self, *args):
        out_params = (getattr(self.ns.module, "HARNESS_OUT_PARAMS", None) or {}).get(self.name)
        pyargs = [to_py_arg(a) for a in args]
        try:
            with lenient(arrays_in(args)):
                ret = self.fn(*pyargs)
        except FbbNotModelled:
            raise
        except TypeError as e:
            raise FbbNotModelled(f"{self.qual}({len(args)} argument(s)): the Python mirror rejected the call: {e}") from e
        if out_params:
            if not isinstance(ret, tuple) or len(ret) != 1 + len(out_params):
                raise FbbNotModelled(f"{self.qual}: HARNESS_OUT_PARAMS {tuple(out_params)} needs a "
                                     f"(result, {len(out_params)} new value(s)) tuple")
            ret, *new = ret
            for idx, value in zip(out_params, new):
                target = args[idx]
                if isinstance(target, FbArray):
                    target.assign_from(value)
                elif isinstance(target, PodValue):
                    for k, v in (value if isinstance(value, dict) else dataclasses.asdict(value)).items():
                        setattr(target, k, v)
                else:
                    raise FbbNotModelled(f"{self.qual}: out-parameter {idx} is not an array / struct")
        return from_py_result(ret)


class FbcapNamespace:
    """ecco_fbcap:: (or, with `default_module="fallback_save", ns="ecco_fbsave"`, ecco_fbsave::), bound to one FbbSim and
    one Python mirror module imported lazily on the first lookup."""

    def __init__(self, sim, module=None, *, default_module="fallback_capture", ns="ecco_fbcap"):
        self._sim = sim
        self._spec = module
        self._module = None
        self._default = default_module
        self._ns = ns

    @property
    def module(self):
        if self._module is None:
            m = self._spec
            try:
                if m is None:
                    m = importlib.import_module(self._default)
                elif isinstance(m, str):
                    m = importlib.import_module(m)
            except ImportError as e:
                raise FbbNotModelled(f"{self._ns}:: needs registry/{self._default}.py (the Python mirror of its header): "
                                     f"{e}") from e
            self._module = m
        return self._module

    def _hints(self):
        h = dict(DEFAULT_HARNESS_TYPES)
        h.update(getattr(self.module, "HARNESS_TYPES", None) or {})
        return h

    def lookup(self, path: str):
        parts = path.split("__FBCNS__")
        root = parts[0]
        qual = f"{self._ns}::" + "::".join(parts)
        mod = self.module
        hints = self._hints()
        if root.startswith("_"):
            raise FbbNotModelled(f"{qual}: private names are not part of the header")
        if len(parts) == 1 and root in hints and root not in vars(mod):
            h = hints[root]
            if h[0] != "array":
                raise FbbNotModelled(f"{qual}: HARNESS_TYPES kind {h[0]!r}")
            return ArrayType(qual, h[1], h[2])
        if len(parts) == 1 and root in hints and not (dataclasses.is_dataclass(vars(mod)[root])):
            h = hints[root]
            return ArrayType(qual, h[1], h[2])
        if root not in vars(mod):
            raise FbbNotModelled(f"{qual} is not defined by the Python mirror {mod.__name__} (registry/{self._default}.py)")
        raw = vars(mod)[root]
        for p in parts[1:]:
            if not hasattr(raw, p):
                raise FbbNotModelled(f"{qual}: {p!r} is not a member of {root}")
            raw = getattr(raw, p)
        return self._present(raw, qual, parts[-1])

    def _present(self, obj, qual, name):
        if isinstance(obj, types.ModuleType):
            raise FbbNotModelled(f"{qual} is a module, not a header name")
        if isinstance(obj, (bool, int, float)):
            return obj
        if isinstance(obj, str):
            return FCStr(obj)
        if isinstance(obj, (bytes, bytearray)):
            return FbArray.from_bytes(obj)
        if inspect.isclass(obj):
            if issubclass(obj, enum.Enum):
                return EnumType(qual, obj)
            return PodType(qual, obj)
        if isinstance(obj, (list, tuple)) and not hasattr(obj, "_fields"):
            return ConstArray(list(obj))
        if _is_pod_like(obj):
            return PodValue(copy.deepcopy(obj), None)
        if callable(obj):
            return AdapterFn(self, qual, name, obj)
        raise FbbNotModelled(f"{qual}: a {type(obj).__name__} constant is not modelled")

    def sizeof_of(self, name: str) -> int:
        sizes = getattr(self.module, "HARNESS_SIZEOF", None) or {}
        if name in sizes:
            return int(sizes[name])
        raise FbbNotModelled(f"sizeof({self._ns}::{name}): the mirror has no HARNESS_SIZEOF entry for it")
