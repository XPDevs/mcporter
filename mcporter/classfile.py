"""
Pure-Python Java class-file (.class) parser.

This is a from-scratch implementation of the JVM class-file format
(JVMS §4).  It extracts the constant pool, string constants, referenced
classes/methods, and runtime annotations.  We use it to statically inspect
*compiled* Minecraft mods, which contain no Java source.

We deliberately do not attempt full bytecode decompilation; instead we mine
the constant pool + annotations for registry ids, @Mod metadata, mixin
targets, dependency declarations and other structural hints.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Optional

# constant pool tags
CONST_Utf8 = 1
CONST_Integer = 3
CONST_Float = 4
CONST_Long = 5
CONST_Double = 6
CONST_Class = 7
CONST_String = 8
CONST_Fieldref = 9
CONST_Methodref = 10
CONST_InterfaceMethodref = 11
CONST_NameAndType = 12
CONST_MethodHandle = 15
CONST_MethodType = 16
CONST_Dynamic = 17
CONST_InvokeDynamic = 18
CONST_Module = 19
CONST_Package = 20

_ANNOT_TAGS = {
    "B": "byte", "C": "char", "D": "double", "F": "float", "I": "int",
    "J": "long", "S": "short", "Z": "boolean", "V": "void",
}


class ClassFileError(Exception):
    pass


class _Reader:
    __slots__ = ("d", "p")

    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    def u1(self) -> int:
        v = self.d[self.p]
        self.p += 1
        return v

    def u2(self) -> int:
        v = struct.unpack_from(">H", self.d, self.p)[0]
        self.p += 2
        return v

    def u4(self) -> int:
        v = struct.unpack_from(">I", self.d, self.p)[0]
        self.p += 4
        return v

    def i4(self) -> int:
        v = struct.unpack_from(">i", self.d, self.p)[0]
        self.p += 4
        return v

    def i8(self) -> int:
        v = struct.unpack_from(">q", self.d, self.p)[0]
        self.p += 8
        return v

    def f4(self) -> float:
        v = struct.unpack_from(">f", self.d, self.p)[0]
        self.p += 4
        return v

    def f8(self) -> float:
        v = struct.unpack_from(">d", self.d, self.p)[0]
        self.p += 8
        return v

    def bytes(self, n: int) -> bytes:
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def utf8(self) -> str:
        n = self.u2()
        raw = self.d[self.p:self.p + n]
        self.p += n
        # modified UTF-8: we just decode as utf-8 with surrogatepass fallback
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")


@dataclass
class Annotation:
    type_desc: str
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def type_name(self) -> str:
        t = self.type_desc
        if t.startswith("L") and t.endswith(";"):
            t = t[1:-1]
        return t.replace("/", ".")


@dataclass
class FieldInfo:
    access: int
    name: str
    descriptor: str
    annotations: list[Annotation] = field(default_factory=list)

    @property
    def java_type(self) -> str:
        return _descriptor_to_type(self.descriptor)


@dataclass
class CodeAttr:
    """The JVMS `Code` attribute of a method (raw bytecode + metadata)."""
    max_stack: int
    max_locals: int
    code: bytes
    exception_table: list = field(default_factory=list)
    line_numbers: dict = field(default_factory=dict)


@dataclass
class MethodInfo:
    access: int
    name: str
    descriptor: str
    annotations: list[Annotation] = field(default_factory=list)
    code: Optional[CodeAttr] = None
    throws: list[str] = field(default_factory=list)

    @property
    def param_descriptors(self) -> list[str]:
        return _parse_method_params(self.descriptor)

    @property
    def return_descriptor(self) -> str:
        return _parse_method_return(self.descriptor)

    @property
    def is_static(self) -> bool:
        return bool(self.access & 0x0008)

    @property
    def is_abstract(self) -> bool:
        return bool(self.access & 0x0400) or self.code is None


class ClassFile:
    """Parsed representation of a .class file."""

    def __init__(self, data: bytes, source_name: str = ""):
        self.source_name = source_name
        self.strings: list[str] = []
        self.class_refs: list[str] = []
        self.method_refs: list[str] = []
        self.field_refs: list[str] = []
        self.fields: list[FieldInfo] = []
        self.methods: list[MethodInfo] = []
        self.annotations: list[Annotation] = []
        self.this_class = ""
        self.super_class = ""
        self.interfaces: list[str] = []
        self.major = 0
        self.minor = 0
        self.access = 0
        self.source_file = ""
        self._cp: list = []
        self._cp_count = 0
        self._parse(data)

    # -- constant-pool accessors (used by the bytecode translator) ----------
    def _utf(self, idx: int) -> str:
        if 1 <= idx < self._cp_count:
            e = self._cp[idx]
            if e and e[0] == "utf8":
                return e[1]
        return ""

    def _class_name(self, idx: int) -> str:
        e = self._cp[idx] if 1 <= idx < self._cp_count else None
        if e and e[0] == "ref":
            return self._utf(e[1]).replace("/", ".")
        if e and e[0] == "utf8":
            return e[1].replace("/", ".")
        return ""

    def const_value(self, idx: int):
        """Return the Python value of a constant-pool entry (best effort)."""
        e = self._cp[idx] if 1 <= idx < self._cp_count else None
        if not e:
            return None
        if e[0] in ("int", "float", "long", "double"):
            return e[1]
        if e[0] == "utf8":
            return e[1]
        if e[0] == "ref":
            # Class or String
            inner = self._cp[e[1]] if 1 <= e[1] < self._cp_count else None
            if inner and inner[0] == "utf8":
                return inner[1]
        return None

    def field_ref(self, idx: int) -> tuple[str, str, str]:
        e = self._cp[idx] if 1 <= idx < self._cp_count else None
        if e and e[0] == "ref2":
            _, _tag, a, b = e
            nat = self._cp[b] if 1 <= b < self._cp_count else None
            name = self._utf(nat[2]) if nat and nat[0] == "ref2" else self._utf(b)
            desc = self._utf(nat[3]) if nat and nat[0] == "ref2" else ""
            return self._class_name(a), name, desc
        return "", "", ""

    def method_ref(self, idx: int) -> tuple[str, str, str, bool]:
        e = self._cp[idx] if 1 <= idx < self._cp_count else None
        if e and e[0] == "ref2":
            _, tag, a, b = e
            nat = self._cp[b] if 1 <= b < self._cp_count else None
            name = self._utf(nat[2]) if nat and nat[0] == "ref2" else self._utf(b)
            desc = self._utf(nat[3]) if nat and nat[0] == "ref2" else ""
            return self._class_name(a), name, desc, tag == CONST_InterfaceMethodref
        return "", "", "", False

    # -- public helpers -----------------------------------------------------
    def has_annotation(self, simple_or_full: str) -> bool:
        want = simple_or_full.split(".")[-1]
        return any(a.type_name.split(".")[-1] == want for a in self.annotations)

    def get_annotation(self, simple: str) -> Optional[Annotation]:
        for a in self.annotations:
            if a.type_name.split(".")[-1] == simple:
                return a
        return None

    def field_named(self, name: str) -> Optional[FieldInfo]:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    # -- parsing ------------------------------------------------------------
    def _parse(self, data: bytes) -> None:
        r = _Reader(data)
        magic = r.u4()
        if magic != 0xCAFEBABE:
            raise ClassFileError("bad magic")
        self.minor = r.u2()
        self.major = r.u2()
        cp_count = r.u2()

        # constant pool as list indexed from 1
        cp: list[Any] = [None] * cp_count
        i = 1
        while i < cp_count:
            tag = r.u1()
            if tag == CONST_Utf8:
                cp[i] = ("utf8", r.utf8())
            elif tag == CONST_Integer:
                cp[i] = ("int", r.i4())
            elif tag == CONST_Float:
                cp[i] = ("float", r.f4())
            elif tag == CONST_Long:
                cp[i] = ("long", r.i8())
                i += 1
            elif tag == CONST_Double:
                cp[i] = ("double", r.f8())
                i += 1
            elif tag in (CONST_Class, CONST_String, CONST_MethodType, CONST_Module, CONST_Package):
                cp[i] = ("ref", r.u2())
            elif tag in (CONST_Fieldref, CONST_Methodref, CONST_InterfaceMethodref,
                         CONST_NameAndType, CONST_Dynamic, CONST_InvokeDynamic):
                a = r.u2()
                b = r.u2()
                cp[i] = ("ref2", tag, a, b)
            elif tag == CONST_MethodHandle:
                cp[i] = ("handle", r.u1(), r.u2())
            else:
                raise ClassFileError(f"unknown constant pool tag {tag} at {i}")
            i += 1

        def utf(idx: int) -> str:
            if 1 <= idx < cp_count and cp[idx] and cp[idx][0] == "utf8":
                return cp[idx][1]
            return ""

        # keep the constant pool for the bytecode translator
        self._cp = cp
        self._cp_count = cp_count

        def class_name(idx: int) -> str:
            if 1 <= idx < cp_count and cp[idx] and cp[idx][0] == "ref":
                return utf(cp[idx][1]).replace("/", ".")
            return ""

        # collect interesting constants
        for k in range(1, cp_count):
            e = cp[k]
            if e is None:
                continue
            if e[0] == "utf8":
                s = e[1]
                if s and not s.startswith("(") and len(s) >= 2:
                    self.strings.append(s)
            elif e[0] == "ref2":
                _, tag, a, b = e
                if tag == CONST_Fieldref:
                    self.field_refs.append(f"{class_name(a)}.{utf(b)}")
                elif tag in (CONST_Methodref, CONST_InterfaceMethodref):
                    self.method_refs.append(f"{class_name(a)}.{utf(b)}")
            elif e[0] == "ref":
                pass

        self.access = r.u2()
        this_idx = r.u2()
        super_idx = r.u2()
        self.this_class = class_name(this_idx)
        self.super_class = class_name(super_idx)
        self.class_refs = sorted({c for c in self._all_class_names(cp, cp_count)})

        iface_count = r.u2()
        for _ in range(iface_count):
            self.interfaces.append(class_name(r.u2()))

        # fields
        fields_count = r.u2()
        for _ in range(fields_count):
            access = r.u2()
            name = utf(r.u2())
            desc = utf(r.u2())
            annots = []
            for _a in range(r.u2()):
                aname = utf(r.u2())
                alen = r.u4()
                if aname == "RuntimeVisibleAnnotations":
                    annots = self._parse_annotations(r, utf, alen)
                else:
                    r.bytes(alen)
            self.fields.append(FieldInfo(access, name, desc, annots))

        # methods
        methods_count = r.u2()
        for _ in range(methods_count):
            access = r.u2()
            name = utf(r.u2())
            desc = utf(r.u2())
            annots = []
            code = None
            throws = []
            for _a in range(r.u2()):
                aname = utf(r.u2())
                alen = r.u4()
                if aname == "RuntimeVisibleAnnotations":
                    annots = self._parse_annotations(r, utf, alen)
                elif aname == "Code":
                    code = self._parse_code(r, utf, alen)
                elif aname == "Exceptions":
                    end = r.p + alen
                    for _e in range(r.u2()):
                        throws.append(class_name(r.u2()))
                    r.p = end
                else:
                    r.bytes(alen)
            self.methods.append(MethodInfo(access, name, desc, annots, code, throws))

        # class-level attributes
        for _a in range(r.u2()):
            aname = utf(r.u2())
            alen = r.u4()
            if aname == "RuntimeVisibleAnnotations":
                self.annotations = self._parse_annotations(r, utf, alen)
            elif aname == "SourceFile":
                self.source_file = utf(r.u2())
            else:
                r.bytes(alen)

    def _parse_code(self, r: _Reader, utf, length: int) -> CodeAttr:
        end = r.p + length
        max_stack = r.u2()
        max_locals = r.u2()
        code_len = r.u4()
        code = r.bytes(code_len)
        exc = []
        for _ in range(r.u2()):
            start = r.u2()
            stop = r.u2()
            handler = r.u2()
            ctype = self._class_name(r.u2())
            exc.append((start, stop, handler, ctype))
        line_numbers: dict = {}
        for _ in range(r.u2()):
            aname = utf(r.u2())
            alen = r.u4()
            if aname == "LineNumberTable":
                aend = r.p + alen
                for _ln in range(r.u2()):
                    pc = r.u2()
                    line = r.u2()
                    line_numbers[pc] = line
                r.p = aend
            else:
                r.bytes(alen)
        r.p = end
        return CodeAttr(max_stack, max_locals, code, exc, line_numbers)

    @staticmethod
    def _all_class_names(cp, cp_count) -> list[str]:
        names = []
        for k in range(1, cp_count):
            e = cp[k]
            if e and e[0] == "ref":
                target = cp[e[1]] if 1 <= e[1] < cp_count else None
                if target and target[0] == "utf8":
                    names.append(target[1].replace("/", "."))
        return names

    def _parse_annotations(self, r: _Reader, utf, length: int) -> list[Annotation]:
        end = r.p + length
        out: list[Annotation] = []
        count = r.u2()
        for _ in range(count):
            out.append(self._parse_annotation(r, utf))
        r.p = end
        return out

    def _parse_annotation(self, r: _Reader, utf) -> Annotation:
        type_desc = utf(r.u2())
        annot = Annotation(type_desc)
        num_pairs = r.u2()
        for _ in range(num_pairs):
            name = utf(r.u2())
            annot.values[name] = self._parse_element_value(r, utf)
        return annot

    def _parse_element_value(self, r: _Reader, utf) -> Any:
        tag = chr(r.u1())
        if tag in "BCISZ":
            return r.i4()
        if tag == "D":
            return r.f8()
        if tag == "F":
            return r.f4()
        if tag == "J":
            return r.i8()
        if tag == "s":
            return utf(r.u2())
        if tag == "e":
            return {"enum": utf(r.u2()), "value": utf(r.u2())}
        if tag == "c":
            return {"class": utf(r.u2())}
        if tag == "@":
            return self._parse_annotation(r, utf)
        if tag == "[":
            n = r.u2()
            return [self._parse_element_value(r, utf) for _ in range(n)]
        return None


def _descriptor_to_type(desc: str) -> str:
    desc = desc.strip()
    arr = 0
    while desc.startswith("["):
        arr += 1
        desc = desc[1:]
    if desc.startswith("L") and desc.endswith(";"):
        base = desc[1:-1].replace("/", ".")
    else:
        base = _ANNOT_TAGS.get(desc, desc)
    return base + "[]" * arr


def _parse_method_return(desc: str) -> str:
    if ")" not in desc:
        return "void"
    return _descriptor_to_type(desc[desc.index(")") + 1:])


def _parse_method_params(desc: str) -> list[str]:
    if not desc.startswith("("):
        return []
    out = []
    i = 1
    while i < len(desc) and desc[i] != ")":
        arr = ""
        while desc[i] == "[":
            arr += "[]"
            i += 1
        c = desc[i]
        if c == "L":
            j = desc.index(";", i)
            out.append(desc[i + 1:j].replace("/", ".") + arr)
            i = j + 1
        else:
            out.append(_ANNOT_TAGS.get(c, c) + arr)
            i += 1
    return out
