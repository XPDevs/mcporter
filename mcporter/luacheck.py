"""
A small, dependency-free Lua structural checker.

This is intentionally *not* a full Lua parser.  It lexes the source (skipping
strings, long strings and comments) then verifies:

  * balanced ``( ) { } [ ]``
  * balanced ``do/end`` style blocks (function / if / for / while / repeat)
  * unterminated strings / long brackets / comments

It is used to sanity-check generated mods without shipping a Lua interpreter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class LuaIssue:
    line: int
    message: str


def _lex(text: str) -> tuple[list[tuple[str, int]], list[LuaIssue]]:
    """Return a list of (token, line) for structural tokens, plus issues."""
    tokens: list[tuple[str, int]] = []
    issues: list[LuaIssue] = []
    i = 0
    n = len(text)
    line = 1
    word = ""
    word_line = 1
    KEYWORDS = {"function", "if", "for", "while", "do", "repeat", "end",
                "until", "then", "else", "elseif", "return", "local"}

    def flush():
        nonlocal word
        if word:
            if word in KEYWORDS:
                tokens.append((word, word_line))
            word = ""

    while i < n:
        c = text[i]
        # comments
        if c == "-" and i + 1 < n and text[i + 1] == "-":
            # long comment --[[ ... ]] or --[==[
            j = i + 2
            lvl = _long_bracket_level(text, j)
            if lvl is not None:
                end = _find_long_bracket_end(text, j, lvl)
                if end is None:
                    issues.append(LuaIssue(line, "unterminated block comment"))
                    break
                line += text.count("\n", i, end)
                i = end
                continue
            # line comment
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
            continue
        if c == "\n":
            flush()
            line += 1
            i += 1
            continue
        if c in " \t\r":
            flush()
            i += 1
            continue
        if c == '"' or c == "'":
            flush()
            i, line = _skip_quoted(text, i, c, line, issues)
            continue
        if c == "[":
            lvl = _long_bracket_level(text, i)
            if lvl is not None:
                flush()
                end = _find_long_bracket_end(text, i, lvl)
                if end is None:
                    issues.append(LuaIssue(line, "unterminated long string"))
                    break
                line += text.count("\n", i, end)
                i = end
                continue
        if c.isalpha() or c == "_":
            if not word:
                word_line = line
            word += c
            i += 1
            continue
        if c.isdigit():
            flush()
            i += 1
            continue
        # structural punctuation
        flush()
        if c in "(){}[]":
            tokens.append((c, line))
        i += 1
    flush()
    return tokens, issues


def _long_bracket_level(text: str, i: int) -> int | None:
    if i >= len(text) or text[i] != "[":
        return None
    j = i + 1
    eq = 0
    while j < len(text) and text[j] == "=":
        eq += 1
        j += 1
    if j < len(text) and text[j] == "[":
        return eq
    return None


def _find_long_bracket_end(text: str, i: int, level: int) -> int | None:
    close = "]" + "=" * level + "]"
    idx = text.find(close, i + level + 2)
    if idx == -1:
        return None
    return idx + len(close)


def _skip_quoted(text: str, i: int, quote: str, line: int,
                 issues: list[LuaIssue]) -> tuple[int, int]:
    i += 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "\n":
            line += 1
        if c == quote:
            return i + 1, line
        i += 1
    issues.append(LuaIssue(line, "unterminated string"))
    return i, line


_OPEN_BLOCK = {"function", "if", "for", "while", "repeat"}


def check_source(text: str) -> list[LuaIssue]:
    tokens, issues = _lex(text)
    brackets: list[tuple[str, int]] = []
    pairs = {")": "(", "}": "{", "]": "["}
    block_stack: list[tuple[str, int]] = []

    for tok, ln in tokens:
        if tok in "({[":
            brackets.append((tok, ln))
        elif tok in ")}]":
            if not brackets or brackets[-1][0] != pairs[tok]:
                issues.append(LuaIssue(ln, f"unmatched '{tok}'"))
            else:
                brackets.pop()
        elif tok in _OPEN_BLOCK:
            block_stack.append((tok, ln))
        elif tok == "end":
            if not block_stack:
                issues.append(LuaIssue(ln, "unexpected 'end'"))
            else:
                block_stack.pop()
        elif tok == "until":
            if block_stack and block_stack[-1][0] == "repeat":
                block_stack.pop()
            else:
                issues.append(LuaIssue(ln, "unexpected 'until'"))

    for tok, ln in brackets:
        issues.append(LuaIssue(ln, f"unclosed '{tok}'"))
    for tok, ln in block_stack:
        issues.append(LuaIssue(ln, f"unclosed block '{tok}' (missing 'end')"))
    return sorted(issues, key=lambda x: x.line)


def check_file(path: str) -> list[LuaIssue]:
    with open(path, "r", encoding="utf-8") as fh:
        return check_source(fh.read())


def check_mod(moddir: str) -> dict:
    results = {}
    for base, _dirs, files in os.walk(moddir):
        for f in files:
            if f.endswith(".lua"):
                p = os.path.join(base, f)
                rel = os.path.relpath(p, moddir)
                issues = check_file(p)
                if issues:
                    results[rel] = [f"line {i.line}: {i.message}" for i in issues]
    return results
