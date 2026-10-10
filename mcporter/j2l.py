"""
Java bytecode -> Lua translator (best effort).

Minecraft Java mods ship compiled `.class` files.  When no source is present
we decode the JVM bytecode of every method and emit a *readable reference
translation* to Lua.  This is not a decompiler and not a drop-in runtime: it
recovers the structure (statements, field/method access, arithmetic, returns)
of methods that operate on primitives and simple objects, and it leaves an
explicit `-- ?` marker plus a byte offset comment for anything it does not
understand (switches, complex control flow, invokedynamic/lambdas, ...).

The generated `logic/*.lua` files double as a human-readable map of what the
Java code did, so a porter can finish the runtime behaviour by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .classfile import ClassFile, MethodInfo, _parse_method_params

# ---------------------------------------------------------------------------
# Opcode table: opcode -> (mnemonic, operand-kind)
# ---------------------------------------------------------------------------
_NONE = ""
_OPCODES: dict[int, tuple[str, str]] = {}


def _def(op, name, kind=_NONE):
    _OPCODES[op] = (name, kind)


_def(0x00, "nop")
_def(0x01, "aconst_null")
for _i, _n in enumerate(["iconst_m1", "iconst_0", "iconst_1", "iconst_2", "iconst_3",
                         "iconst_4", "iconst_5"]):
    _def(0x02 + _i, _n)
_def(0x09, "lconst_0"); _def(0x0A, "lconst_1")
_def(0x0B, "fconst_0"); _def(0x0C, "fconst_1"); _def(0x0D, "fconst_2")
_def(0x0E, "dconst_0"); _def(0x0F, "dconst_1")
_def(0x10, "bipush", "i1")
_def(0x11, "sipush", "i2")
_def(0x12, "ldc", "cp1")
_def(0x13, "ldc_w", "cp2")
_def(0x14, "ldc2_w", "cp2")
for _i, _n in enumerate(["iload", "lload", "fload", "dload", "aload"]):
    _def(0x15 + _i, _n, "local1")
for _i, _n in enumerate(["iload_0", "iload_1", "iload_2", "iload_3",
                         "lload_0", "lload_1", "lload_2", "lload_3",
                         "fload_0", "fload_1", "fload_2", "fload_3",
                         "dload_0", "dload_1", "dload_2", "dload_3",
                         "aload_0", "aload_1", "aload_2", "aload_3"]):
    _def(0x1A + _i, _n)
for _i, _n in enumerate(["iaload", "laload", "faload", "daload", "aaload",
                         "baload", "caload", "saload"]):
    _def(0x2E + _i, _n)
for _i, _n in enumerate(["istore", "lstore", "fstore", "dstore", "astore"]):
    _def(0x36 + _i, _n, "local1")
for _i, _n in enumerate(["istore_0", "istore_1", "istore_2", "istore_3",
                         "lstore_0", "lstore_1", "lstore_2", "lstore_3",
                         "fstore_0", "fstore_1", "fstore_2", "fstore_3",
                         "dstore_0", "dstore_1", "dstore_2", "dstore_3",
                         "astore_0", "astore_1", "astore_2", "astore_3"]):
    _def(0x3B + _i, _n)
for _i, _n in enumerate(["iastore", "lastore", "fastore", "dastore", "aastore",
                         "bastore", "castore", "sastore"]):
    _def(0x4F + _i, _n)
for _i, _n in enumerate(["pop", "pop2", "dup", "dup_x1", "dup_x2", "dup2",
                         "dup2_x1", "dup2_x2", "swap"]):
    _def(0x57 + _i, _n)
for _i, _n in enumerate(["iadd", "ladd", "fadd", "dadd",
                         "isub", "lsub", "fsub", "dsub",
                         "imul", "lmul", "fmul", "dmul",
                         "idiv", "ldiv", "fdiv", "ddiv",
                         "irem", "lrem", "frem", "drem",
                         "ineg", "lneg", "fneg", "dneg",
                         "ishl", "lshl", "ishr", "lshr",
                         "iushr", "lushr", "iand", "land",
                         "ior", "lor", "ixor", "lxor"]):
    _def(0x60 + _i, _n)
_def(0x84, "iinc", "iinc")
for _i, _n in enumerate(["i2l", "i2f", "i2d", "l2i", "l2f", "l2d", "f2i", "f2l",
                         "f2d", "d2i", "d2l", "d2f", "i2b", "i2c", "i2s"]):
    _def(0x85 + _i, _n)
for _i, _n in enumerate(["lcmp", "fcmpl", "fcmpg", "dcmpl", "dcmpg"]):
    _def(0x94 + _i, _n)
for _i, _n in enumerate(["ifeq", "ifne", "iflt", "ifge", "ifgt", "ifle",
                         "if_icmpeq", "if_icmpne", "if_icmplt", "if_icmpge",
                         "if_icmpgt", "if_icmple", "if_acmpeq", "if_acmpne"]):
    _def(0x99 + _i, _n, "br2")
_def(0xA7, "goto", "br2")
_def(0xA8, "jsr", "br2")
_def(0xA9, "ret", "local1")
_def(0xAA, "tableswitch", "switch")
_def(0xAB, "lookupswitch", "switch")
for _i, _n in enumerate(["ireturn", "lreturn", "freturn", "dreturn", "areturn", "return"]):
    _def(0xAC + _i, _n)
_def(0xB2, "getstatic", "cp2")
_def(0xB3, "putstatic", "cp2")
_def(0xB4, "getfield", "cp2")
_def(0xB5, "putfield", "cp2")
_def(0xB6, "invokevirtual", "cp2")
_def(0xB7, "invokespecial", "cp2")
_def(0xB8, "invokestatic", "cp2")
_def(0xB9, "invokeinterface", "invokeinterface")
_def(0xBA, "invokedynamic", "invokedynamic")
_def(0xBB, "new", "cp2")
_def(0xBC, "newarray", "newarray")
_def(0xBD, "anewarray", "cp2")
_def(0xBE, "arraylength")
_def(0xBF, "athrow")
_def(0xC0, "checkcast", "cp2")
_def(0xC1, "instanceof", "cp2")
_def(0xC2, "monitorenter")
_def(0xC3, "monitorexit")
_def(0xC4, "wide", "wide")
_def(0xC5, "multianewarray", "multianewarray")
_def(0xC6, "ifnull", "br2")
_def(0xC7, "ifnonnull", "br2")
_def(0xC8, "goto_w", "br4")
_def(0xC9, "jsr_w", "br4")

_BRANCH_OPS = {0x99, 0x9A, 0x9B, 0x9C, 0x9D, 0x9E, 0x9F, 0xA0, 0xA1, 0xA2,
               0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xC6, 0xC7, 0xC8, 0xC9}
_RETURN_OPS = {0xAC, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1}

_VAR_RE = None


_LUA_KEYWORDS = {"nil", "true", "false", "and", "or", "not", "function",
                 "end", "then", "else", "elseif", "for", "while", "repeat",
                 "until", "do", "local", "return", "break", "in", "goto"}


def _is_var(expr: str) -> bool:
    """True if `expr` may legally appear on the left of `=` in Lua."""
    global _VAR_RE
    if _VAR_RE is None:
        import re
        _VAR_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*|\([^()\n]*\))"
                             r"(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[^\[\]{}\n]+\])*$")
    e = (expr or "").strip()
    if e in _LUA_KEYWORDS:
        return False
    return bool(_VAR_RE.match(e))


def _prefix(expr: str) -> str:
    """Ensure `expr` is usable as a Lua prefix-expression (for `:method()`)."""
    e = (expr or "nil").strip()
    if _is_var(e):
        return e
    if e.startswith("(") and e.endswith(")"):
        return e
    return f"({e})"



@dataclass
class Instruction:
    offset: int
    opcode: int
    mnemonic: str
    operands: tuple
    size: int


def decode(code: bytes, cf: ClassFile) -> list[Instruction]:
    """Decode a method body into instructions.  Raises on malformed input."""
    out: list[Instruction] = []
    i = 0
    n = len(code)
    while i < n:
        start = i
        op = code[i]
        i += 1
        name, kind = _OPCODES.get(op, ("unknown_0x%02x" % op, _NONE))
        ops: tuple = ()
        if kind == "u1" or kind == "cp1" or kind == "local1" or kind == "newarray":
            ops = (code[i],)
            i += 1
        elif kind in ("u2", "cp2", "br2", "i2"):
            ops = (int.from_bytes(code[i:i + 2], "big", signed=(kind == "i2")),)
            i += 2
        elif kind == "i1":
            v = code[i]
            if v > 127:
                v -= 256
            ops = (v,)
            i += 1
        elif kind == "br4":
            ops = (int.from_bytes(code[i:i + 4], "big", signed=True),)
            i += 4
        elif kind == "iinc":
            ops = (code[i], code[i + 1] if i + 1 < n else 0)
            i += 2
        elif kind == "invokeinterface":
            ops = (int.from_bytes(code[i:i + 2], "big"), code[i + 2], code[i + 3])
            i += 4
        elif kind == "invokedynamic":
            ops = (int.from_bytes(code[i:i + 2], "big"), int.from_bytes(code[i + 2:i + 4], "big"))
            i += 4
        elif kind == "multianewarray":
            ops = (int.from_bytes(code[i:i + 2], "big"), code[i + 2])
            i += 3
        elif kind == "wide":
            wop = code[i]
            i += 1
            wname, _wkind = _OPCODES.get(wop, ("unknown", _NONE))
            if wop == 0x84:
                idx = int.from_bytes(code[i:i + 2], "big")
                const = int.from_bytes(code[i + 2:i + 4], "big", signed=True)
                i += 4
                name, ops = "iinc", (idx, const)
            else:
                idx = int.from_bytes(code[i:i + 2], "big")
                i += 2
                name, ops = wname, (idx,)
        elif kind == "switch":
            # padding to 4-byte boundary relative to method start
            while (i % 4) != 0:
                i += 1
            default = int.from_bytes(code[i:i + 4], "big", signed=True)
            i += 4
            if op == 0xAA:  # tableswitch
                low = int.from_bytes(code[i:i + 4], "big", signed=True)
                high = int.from_bytes(code[i:i + 4], "big", signed=True)
                i += 8
                count = max(0, high - low + 1)
                jumps = []
                for _ in range(count):
                    jumps.append(int.from_bytes(code[i:i + 4], "big", signed=True))
                    i += 4
                ops = (default, low, high, tuple(jumps))
            else:  # lookupswitch
                npairs = int.from_bytes(code[i:i + 4], "big", signed=True)
                i += 4
                pairs = []
                for _ in range(max(0, npairs)):
                    key = int.from_bytes(code[i:i + 4], "big", signed=True)
                    off = int.from_bytes(code[i + 4:i + 8], "big", signed=True)
                    i += 8
                    pairs.append((key, off))
                ops = (default, tuple(pairs))
        out.append(Instruction(start, op, name, ops, i - start))
    return out


# ---------------------------------------------------------------------------
# Translator
# ---------------------------------------------------------------------------
_NUMERIC = {"iadd": "+", "ladd": "+", "fadd": "+", "dadd": "+",
            "isub": "-", "lsub": "-", "fsub": "-", "dsub": "-",
            "imul": "*", "lmul": "*", "fmul": "*", "dmul": "*",
            "idiv": "/", "ldiv": "/", "fdiv": "/", "ddiv": "/",
            "irem": "%", "lrem": "%", "frem": "%", "drem": "%",
            "iand": "b_and", "land": "b_and", "ior": "b_or", "lor": "b_or",
            "ixor": "b_xor", "lxor": "b_xor", "ishl": "b_lshift",
            "ishr": "b_arshift", "iushr": "b_rshift"}

_CMP_OPS = {"if_icmpeq": "==", "if_icmpne": "~=", "if_icmplt": "<",
            "if_icmpge": ">=", "if_icmpgt": ">", "if_icmple": "<=",
            "if_acmpeq": "==", "if_acmpne": "~="}
_ZERO_OPS = {"ifeq": "==", "ifne": "~=", "iflt": "<", "ifge": ">=",
             "ifgt": ">", "ifle": "<=", "ifnull": "==", "ifnonnull": "~="}


@dataclass
class J2LStats:
    classes: int = 0
    methods: int = 0
    translated_methods: int = 0
    instructions: int = 0
    translated_instructions: int = 0
    unsupported: dict = field(default_factory=dict)


def _lua_ident(name: str) -> str:
    out = []
    for ch in name:
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    s = "".join(out)
    if s and s[0].isdigit():
        s = "_" + s
    if s in _LUA_KEYWORDS:
        s += "_"
    return s or "_"


def _lua_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


class _MethodTranslator:
    def __init__(self, cf: ClassFile, m: MethodInfo):
        self.cf = cf
        self.m = m
        self.stack: list[str] = []
        self.lines: list[str] = []
        self.translated = 0
        self.unsupported: dict[str, int] = {}
        self.is_static = m.is_static
        self.n_locals = m.code.max_locals if m.code else 0
        self.temp = 0

    def _new_temp(self, hint: str = "arr") -> str:
        self.temp += 1
        return f"_{hint}{self.temp}"

    # -- stack helpers ------------------------------------------------------
    def push(self, expr: str) -> None:
        self.stack.append(expr)

    def pop(self, default: str = "nil") -> str:
        return self.stack.pop() if self.stack else default

    def local(self, idx: int) -> str:
        if idx == 0 and not self.is_static:
            return "self"
        return f"v{idx}"

    def mark(self, ins: Instruction) -> None:
        self.unsupported[ins.mnemonic] = self.unsupported.get(ins.mnemonic, 0) + 1
        self.lines.append(f"    -- ? {ins.mnemonic} @{ins.offset} (not translated)")

    # -- main ---------------------------------------------------------------
    def run(self) -> None:
        try:
            insns = decode(self.m.code.code, self.cf)
        except Exception as exc:  # noqa: BLE001
            self.lines.append(f"    -- ! bytecode decode failed: {exc}")
            return
        for ins in insns:
            self.translated += 1
            handler = getattr(self, "op_" + ins.mnemonic, None)
            if handler is None:
                self.mark(ins)
                continue
            try:
                handler(ins)
            except Exception:  # noqa: BLE001
                self.mark(ins)

    # -- constants ----------------------------------------------------------
    def op_nop(self, ins): pass

    def op_aconst_null(self, ins): self.push("nil")

    def op_iconst_m1(self, ins): self.push("-1")

    def op_iconst_0(self, ins): self.push("0")
    def op_iconst_1(self, ins): self.push("1")
    def op_iconst_2(self, ins): self.push("2")
    def op_iconst_3(self, ins): self.push("3")
    def op_iconst_4(self, ins): self.push("4")
    def op_iconst_5(self, ins): self.push("5")
    def op_lconst_0(self, ins): self.push("0")
    def op_lconst_1(self, ins): self.push("1")
    def op_fconst_0(self, ins): self.push("0.0")
    def op_fconst_1(self, ins): self.push("1.0")
    def op_fconst_2(self, ins): self.push("2.0")
    def op_dconst_0(self, ins): self.push("0.0")
    def op_dconst_1(self, ins): self.push("1.0")

    def op_bipush(self, ins): self.push(str(ins.operands[0]))
    def op_sipush(self, ins): self.push(str(ins.operands[0]))

    def op_ldc(self, ins):
        v = self.cf.const_value(ins.operands[0])
        self.push(self._const(v))

    def op_ldc_w(self, ins):
        v = self.cf.const_value(ins.operands[0])
        self.push(self._const(v))

    def op_ldc2_w(self, ins):
        v = self.cf.const_value(ins.operands[0])
        self.push(self._const(v))

    @staticmethod
    def _const(v) -> str:
        if v is None:
            return "nil"
        if isinstance(v, str):
            return _lua_str(v)
        if isinstance(v, bool):
            return "true" if v else "false"
        return repr(v)

    # -- loads / stores -----------------------------------------------------
    def _load(self, idx): self.push(self.local(idx))
    def op_iload(self, ins): self._load(ins.operands[0])
    def op_lload(self, ins): self._load(ins.operands[0])
    def op_fload(self, ins): self._load(ins.operands[0])
    def op_dload(self, ins): self._load(ins.operands[0])
    def op_aload(self, ins): self._load(ins.operands[0])
    def op_iload_0(self, ins): self._load(0)
    def op_iload_1(self, ins): self._load(1)
    def op_iload_2(self, ins): self._load(2)
    def op_iload_3(self, ins): self._load(3)
    def op_lload_0(self, ins): self._load(0)
    def op_lload_1(self, ins): self._load(1)
    def op_lload_2(self, ins): self._load(2)
    def op_lload_3(self, ins): self._load(3)
    def op_fload_0(self, ins): self._load(0)
    def op_fload_1(self, ins): self._load(1)
    def op_fload_2(self, ins): self._load(2)
    def op_fload_3(self, ins): self._load(3)
    def op_dload_0(self, ins): self._load(0)
    def op_dload_1(self, ins): self._load(1)
    def op_dload_2(self, ins): self._load(2)
    def op_dload_3(self, ins): self._load(3)
    def op_aload_0(self, ins): self._load(0)
    def op_aload_1(self, ins): self._load(1)
    def op_aload_2(self, ins): self._load(2)
    def op_aload_3(self, ins): self._load(3)

    def _store(self, idx):
        self._assign(self.local(idx), self.pop())

    def _assign(self, target: str, value: str) -> None:
        if _is_var(target):
            self.lines.append(f"    {target} = {value}")
        else:
            self.lines.append(f"    -- assign {target} = {value}")

    def op_istore(self, ins): self._store(ins.operands[0])
    def op_lstore(self, ins): self._store(ins.operands[0])
    def op_fstore(self, ins): self._store(ins.operands[0])
    def op_dstore(self, ins): self._store(ins.operands[0])
    def op_astore(self, ins): self._store(ins.operands[0])
    def op_istore_0(self, ins): self._store(0)
    def op_istore_1(self, ins): self._store(1)
    def op_istore_2(self, ins): self._store(2)
    def op_istore_3(self, ins): self._store(3)
    def op_lstore_0(self, ins): self._store(0)
    def op_lstore_1(self, ins): self._store(1)
    def op_lstore_2(self, ins): self._store(2)
    def op_lstore_3(self, ins): self._store(3)
    def op_fstore_0(self, ins): self._store(0)
    def op_fstore_1(self, ins): self._store(1)
    def op_fstore_2(self, ins): self._store(2)
    def op_fstore_3(self, ins): self._store(3)
    def op_dstore_0(self, ins): self._store(0)
    def op_dstore_1(self, ins): self._store(1)
    def op_dstore_2(self, ins): self._store(2)
    def op_dstore_3(self, ins): self._store(3)
    def op_astore_0(self, ins): self._store(0)
    def op_astore_1(self, ins): self._store(1)
    def op_astore_2(self, ins): self._store(2)
    def op_astore_3(self, ins): self._store(3)

    def op_iinc(self, ins):
        idx, const = ins.operands
        self.lines.append(f"    {self.local(idx)} = {self.local(idx)} + {const}")

    # -- stack manipulation -------------------------------------------------
    def op_pop(self, ins): self.pop()
    def op_pop2(self, ins): self.pop()
    def op_dup(self, ins): self.push(self.stack[-1] if self.stack else "nil")
    def op_dup_x1(self, ins):
        a = self.pop(); b = self.pop()
        self.push(a); self.push(b); self.push(a)
    def op_dup_x2(self, ins): self.op_dup_x1(ins)
    def op_dup2(self, ins): self.op_dup(ins)
    def op_dup2_x1(self, ins): self.op_dup_x1(ins)
    def op_dup2_x2(self, ins): self.op_dup_x1(ins)
    def op_swap(self, ins):
        a = self.pop(); b = self.pop()
        self.push(a); self.push(b)

    # -- arithmetic ---------------------------------------------------------
    def _binop(self, ins):
        op = _NUMERIC[ins.mnemonic]
        b = self.pop(); a = self.pop()
        if op in ("b_and", "b_or", "b_xor", "b_lshift", "b_arshift", "b_rshift"):
            fn = {"b_and": "band", "b_or": "bor", "b_xor": "bxor",
                  "b_lshift": "lshift", "b_arshift": "arshift",
                  "b_rshift": "rshift"}[op]
            self.push(f"bit.{fn}({a}, {b})")
        else:
            self.push(f"({a} {op} {b})")

    def op_iadd(self, ins): self._binop(ins)
    def op_isub(self, ins): self._binop(ins)
    def op_imul(self, ins): self._binop(ins)
    def op_idiv(self, ins): self._binop(ins)
    def op_irem(self, ins): self._binop(ins)
    def op_iand(self, ins): self._binop(ins)
    def op_ior(self, ins): self._binop(ins)
    def op_ixor(self, ins): self._binop(ins)
    def op_ishl(self, ins): self._binop(ins)
    def op_ishr(self, ins): self._binop(ins)
    def op_iushr(self, ins): self._binop(ins)
    def op_ladd(self, ins): self._binop(ins)
    def op_lsub(self, ins): self._binop(ins)
    def op_lmul(self, ins): self._binop(ins)
    def op_ldiv(self, ins): self._binop(ins)
    def op_lrem(self, ins): self._binop(ins)
    def op_fadd(self, ins): self._binop(ins)
    def op_fsub(self, ins): self._binop(ins)
    def op_fmul(self, ins): self._binop(ins)
    def op_fdiv(self, ins): self._binop(ins)
    def op_dadd(self, ins): self._binop(ins)
    def op_dsub(self, ins): self._binop(ins)
    def op_dmul(self, ins): self._binop(ins)
    def op_ddiv(self, ins): self._binop(ins)

    def _unop(self, ins, op):
        self.push(f"({op}{self.pop()})")

    def op_ineg(self, ins): self._unop(ins, "-")
    def op_lneg(self, ins): self._unop(ins, "-")
    def op_fneg(self, ins): self._unop(ins, "-")
    def op_dneg(self, ins): self._unop(ins, "-")

    def op_i2b(self, ins): self.push(f"bit.band({self.pop()}, 0xff)")
    def op_i2c(self, ins): self.push(f"bit.band({self.pop()}, 0xffff)")
    def op_i2s(self, ins): self.push(f"bit.band({self.pop()}, 0xffff)")
    def op_i2l(self, ins): self._conv()
    def op_i2f(self, ins): self._conv()
    def op_i2d(self, ins): self._conv()
    def op_l2i(self, ins): self._conv()
    def op_l2f(self, ins): self._conv()
    def op_l2d(self, ins): self._conv()
    def op_f2i(self, ins): self._conv()
    def op_f2l(self, ins): self._conv()
    def op_f2d(self, ins): self._conv()
    def op_d2i(self, ins): self._conv()
    def op_d2l(self, ins): self._conv()
    def op_d2f(self, ins): self._conv()

    def _conv(self):
        if self.stack:
            self.push(self.stack.pop())

    # -- fields -------------------------------------------------------------
    def op_getstatic(self, ins):
        cls, name, _desc = self.cf.field_ref(ins.operands[0])
        self.push(f"{_lua_ident(cls.split('.')[-1])}.{_lua_ident(name)}")

    def op_putstatic(self, ins):
        cls, name, _desc = self.cf.field_ref(ins.operands[0])
        self._assign(f"{_lua_ident(cls.split('.')[-1])}.{_lua_ident(name)}", self.pop())

    def op_getfield(self, ins):
        _cls, name, _desc = self.cf.field_ref(ins.operands[0])
        self.push(f"{_prefix(self.pop())}.{_lua_ident(name)}")

    def op_putfield(self, ins):
        _cls, name, _desc = self.cf.field_ref(ins.operands[0])
        value = self.pop()
        obj = self.pop()
        self._assign(f"{_prefix(obj)}.{_lua_ident(name)}", value)

    # -- invokes ------------------------------------------------------------
    def _args(self, desc: str) -> list[str]:
        n = len(_parse_method_params(desc))
        out = []
        for _ in range(min(n, len(self.stack))):
            out.insert(0, self.pop())
        return out

    def op_invokevirtual(self, ins):
        cls, name, desc, _iface = self.cf.method_ref(ins.operands[0])
        args = self._args(desc)
        obj = self.pop("nil")
        if name == "<init>":
            self.lines.append(f"    -- {_lua_ident(cls.split('.')[-1])}:new({', '.join(args)})")
            return
        self.push(f"{_prefix(obj)}:{_lua_ident(name)}({', '.join(args)})")

    def op_invokespecial(self, ins):
        cls, name, desc, _iface = self.cf.method_ref(ins.operands[0])
        args = self._args(desc)
        obj = self.pop("nil")
        if name == "<init>":
            self.lines.append(f"    -- <init> {_lua_ident(cls.split('.')[-1])}({', '.join(args)})")
            return
        self.push(f"{_prefix(obj)}:{_lua_ident(name)}({', '.join(args)})")

    def op_invokestatic(self, ins):
        cls, name, desc, _iface = self.cf.method_ref(ins.operands[0])
        args = self._args(desc)
        self.push(f"{_lua_ident(cls.split('.')[-1])}.{_lua_ident(name)}({', '.join(args)})")

    def op_invokeinterface(self, ins):
        self.op_invokevirtual(ins)

    def op_invokedynamic(self, ins):
        # lambdas / method handles: no faithful Lua equivalent
        self.lines.append("    -- ? invokedynamic (lambda/method handle) - not translated")

    # -- objects / arrays ---------------------------------------------------
    def op_new(self, ins):
        cls = self.cf._class_name(ins.operands[0])
        self.push(f"{_lua_ident(cls.split('.')[-1])}:new()")

    def op_anewarray(self, ins):
        self.pop()
        name = self._new_temp("arr")
        self.lines.append(f"    local {name} = {{}}")
        self.push(name)

    def op_newarray(self, ins):
        self.pop()
        name = self._new_temp("arr")
        self.lines.append(f"    local {name} = {{}}")
        self.push(name)

    def op_multianewarray(self, ins):
        dims = ins.operands[1]
        for _ in range(dims):
            self.pop()
        name = self._new_temp("arr")
        self.lines.append(f"    local {name} = {{}}")
        self.push(name)

    def op_arraylength(self, ins):
        self.push(f"#{_prefix(self.pop())}")

    def op_iaload(self, ins): self._aload()
    def op_laload(self, ins): self._aload()
    def op_faload(self, ins): self._aload()
    def op_daload(self, ins): self._aload()
    def op_aaload(self, ins): self._aload()
    def op_baload(self, ins): self._aload()
    def op_caload(self, ins): self._aload()
    def op_saload(self, ins): self._aload()
    def op_iastore(self, ins): self._astore()
    def op_lastore(self, ins): self._astore()
    def op_fastore(self, ins): self._astore()
    def op_dastore(self, ins): self._astore()
    def op_aastore(self, ins): self._astore()
    def op_bastore(self, ins): self._astore()
    def op_castore(self, ins): self._astore()
    def op_sastore(self, ins): self._astore()

    def _aload(self):
        idx = self.pop(); arr = self.pop()
        self.push(f"{_prefix(arr)}[{idx}]")

    def _astore(self):
        val = self.pop(); idx = self.pop(); arr = self.pop()
        self._assign(f"{_prefix(arr)}[{idx}]", val)

    # -- comparisons / control flow ----------------------------------------
    def _branch(self, ins, cond: str) -> None:
        target = ins.offset + ins.operands[0]
        self.lines.append(f"    -- if {cond} then goto @{target} end")

    def op_ifeq(self, ins): self._branch(ins, f"{self.pop()} == 0")
    def op_ifne(self, ins): self._branch(ins, f"{self.pop()} ~= 0")
    def op_iflt(self, ins): self._branch(ins, f"{self.pop()} < 0")
    def op_ifge(self, ins): self._branch(ins, f"{self.pop()} >= 0")
    def op_ifgt(self, ins): self._branch(ins, f"{self.pop()} > 0")
    def op_ifle(self, ins): self._branch(ins, f"{self.pop()} <= 0")
    def op_ifnull(self, ins): self._branch(ins, f"{self.pop()} == nil")
    def op_ifnonnull(self, ins): self._branch(ins, f"{self.pop()} ~= nil")

    def _branch_cmp(self, ins, sym: str) -> None:
        b = self.pop(); a = self.pop()
        self._branch(ins, f"{a} {sym} {b}")

    def op_if_icmpeq(self, ins): self._branch_cmp(ins, "==")
    def op_if_icmpne(self, ins): self._branch_cmp(ins, "~=")
    def op_if_icmplt(self, ins): self._branch_cmp(ins, "<")
    def op_if_icmpge(self, ins): self._branch_cmp(ins, ">=")
    def op_if_icmpgt(self, ins): self._branch_cmp(ins, ">")
    def op_if_icmple(self, ins): self._branch_cmp(ins, "<=")
    def op_if_acmpeq(self, ins): self._branch_cmp(ins, "==")
    def op_if_acmpne(self, ins): self._branch_cmp(ins, "~=")

    def op_goto(self, ins):
        self.lines.append(f"    -- goto @{ins.offset + ins.operands[0]}")

    def op_goto_w(self, ins):
        self.lines.append(f"    -- goto @{ins.offset + ins.operands[0]}")

    def op_lcmp(self, ins): self._cmp()
    def op_fcmpl(self, ins): self._cmp()
    def op_fcmpg(self, ins): self._cmp()
    def op_dcmpl(self, ins): self._cmp()
    def op_dcmpg(self, ins): self._cmp()

    def _cmp(self):
        b = self.pop(); a = self.pop()
        self.push(f"(({a} < {b}) and -1 or (({a} > {b}) and 1 or 0))")

    def op_athrow(self, ins):
        self.lines.append(f"    error({self.pop()})")

    def op_checkcast(self, ins):
        pass  # value already on stack; type is only relevant at runtime

    def op_instanceof(self, ins):
        cls = self.cf._class_name(ins.operands[0])
        self.push(f"({self.pop()}.__type == {_lua_str(cls)})")

    def op_monitorenter(self, ins): pass
    def op_monitorexit(self, ins): pass

    def op_tableswitch(self, ins):
        key = self.pop()
        default, low, high, jumps = ins.operands
        self.lines.append(f"    -- switch ({key}) [tableswitch {low}..{high}] "
                          f"default=goto @{ins.offset + default}")

    def op_lookupswitch(self, ins):
        key = self.pop()
        default, pairs = ins.operands
        self.lines.append(f"    -- switch ({key}) [lookupswitch {len(pairs)} cases] "
                          f"default=goto @{ins.offset + default}")

    # -- returns ------------------------------------------------------------
    def _return(self, value: bool):
        # `return` must be the last statement of a Lua block, so wrap it.
        if value:
            self.lines.append(f"    do return {self.pop()} end")
        else:
            self.lines.append("    do return end")

    def op_ireturn(self, ins): self._return(True)
    def op_lreturn(self, ins): self._return(True)
    def op_freturn(self, ins): self._return(True)
    def op_dreturn(self, ins): self._return(True)
    def op_areturn(self, ins): self._return(True)
    def op_return(self, ins): self._return(False)


def _method_header(cf: ClassFile, m: MethodInfo) -> str:
    params = m.param_descriptors
    names = ["self"] if not m.is_static else []
    names += [f"v{i + (0 if m.is_static else 1)}" for i in range(len(params))]
    ret = "  -- returns " + (m.descriptor.split(")")[-1] or "V")
    return (f"function {_lua_ident(cf.this_class.split('.')[-1])}"
            f":{_lua_ident(m.name)}({', '.join(names)}){ret}")


def class_to_lua(cf: ClassFile, stats: J2LStats) -> str:
    """Translate one parsed class into a Lua module (reference translation)."""
    cname = _lua_ident(cf.this_class.split(".")[-1])
    stats.classes += 1
    out = [
        f"-- Java class -> Lua reference translation",
        f"--   class  : {cf.this_class or cname}",
        f"--   super  : {cf.super_class}".rstrip(),
        f"--   source : {cf.source_file or '(compiled)'}",
        "",
        f"{cname} = rawget(_G, {_lua_str(cname)}) or {{}}",
    ]
    if cf.super_class:
        out.append(f"{cname}.__super = {_lua_str(cf.super_class)}")
    for f in cf.fields[:64]:
        out.append(f"{cname}.{_lua_ident(f.name)} = {cname}.{_lua_ident(f.name)}")
    out.append("")
    for m in cf.methods:
        stats.methods += 1
        if m.name == "<clinit>":
            out.append(f"-- static initializer of {cname}")
        if m.is_abstract:
            out.append(_method_header(cf, m))
            out.append("    -- (abstract / native: no bytecode)")
            out.append("end")
            out.append("")
            continue
        tr = _MethodTranslator(cf, m)
        tr.run()
        stats.translated_methods += 1
        for k, v in tr.unsupported.items():
            stats.unsupported[k] = stats.unsupported.get(k, 0) + v
        out.append(_method_header(cf, m))
        if m.code:
            stats.instructions += len(decode(m.code.code, cf)) if m.code.code else 0
        for ln in (tr.lines or ["    -- (empty)"]):
            stmt = ln.rstrip()
            # A trailing `;` stops Lua from gluing this statement onto the next
            # line when the next line starts with `(` / `[` / a string literal.
            if stmt and not stmt.lstrip().startswith("--") and not stmt.endswith(";"):
                stmt += ";"
            out.append(stmt)
        out.append("end")
        out.append("")
    return "\n".join(out)


def translate_classes(classes: list[tuple[str, bytes]], stats: Optional[J2LStats] = None
                      ) -> dict[str, str]:
    """Translate many (path, bytes) class files.

    Returns a mapping of relative Lua filename -> Lua source.  Malformed class
    files are skipped silently; translation never raises.
    """
    from .classfile import ClassFileError
    stats = stats if stats is not None else J2LStats()
    files: dict[str, str] = {}
    used: set[str] = set()
    for path, data in classes:
        try:
            cf = ClassFile(data, path)
        except (ClassFileError, Exception):  # noqa: BLE001
            continue
        if not cf.this_class:
            continue
        base = _lua_ident(cf.this_class.split(".")[-1])
        name = base
        i = 2
        while name in used:
            name = f"{base}_{i}"
            i += 1
        used.add(name)
        try:
            files[f"logic/{name}.lua"] = class_to_lua(cf, stats)
        except Exception:  # noqa: BLE001
            continue
    return files
