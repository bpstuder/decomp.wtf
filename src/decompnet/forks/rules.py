"""The [match] rules, checked on the source of a function whose bytes already agree.

Score 0 only says the bytes are identical. A function can get there with a trick that hides the real
type (an offset cast), with a vtable padded until a layout comes out right, or with code invented to
move the score (an empty block, a do { } while (0)). These are the decompilation skill set's rules:
R4 no offset casts, R13 real vtables, R17 no fake code, R18 no asm. A match has to pass all of them as
well as the bytes, so a byte-exact source that trips one reads MATCH-PENDING — the bytes are banked,
the source is flagged — and not MATCHED.

Heuristic on purpose: every finding names its rule, its line and the fakematch it points at, and
nothing here changes a byte comparison or rewrites a source. The worst a false positive does is send a
real match to a person instead of calling it done.

shortcut: `volatile` on its own is never a finding (MMIO needs it, and a local's can't be told from a
carrier by text; an aliasing volatile cast is already R4). An offset cast into a raw byte buffer (zlib's
unaligned word reads, a save file at `buf + 16`) is flagged like any other: R4 is the letter of the rule
and MATCH-PENDING banks the bytes, so a person decides. Upgrade when a project shows genuine buffer
access being flagged often enough to drown the real tricks.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class Finding(NamedTuple):
    rule: str   # R4 | R13 | R17 | R18
    line: int   # 1-based, in the text check() was given
    code: str   # the line, as it was written
    why: str    # the fakematch it points at


# A type as C writes it: qualifiers and a tag, one name ("u32", "struct Player", "Player").
_TYPE = r"(?:const\s+|volatile\s+|unsigned\s+|signed\s+|struct\s+|class\s+)*[A-Za-z_]\w*"
# Buffer walking through a byte pointer is real code (`(u8*)buf + n`), not an offset fake: only a cast to
# something wider hides a member.
_NOT_A_BYTE_PTR = r"(?![us]?int8_t|[us]8\b|char\b|void\b|byte\b)"

_OFFSET_DEREF = re.compile(r"\*\s*\(\s*" + _TYPE + r"\s*\*\s*\)\s*&")                    # *(u32*)&x
_OFFSET_ADDR = re.compile(r"\(\s*" + _NOT_A_BYTE_PTR + _TYPE + r"\s*\*\s*\)\s*&\s*[A-Za-z_]\w*")  # (u32*)&x
# `(T*)x + n` and `(T*)(x + n)`: an offset into a cast pointer. Not `(T*)p->member`, which is a plain downcast.
_OFFSET_BASE = re.compile(r"\(\s*" + _NOT_A_BYTE_PTR + _TYPE + r"\s*\*\s*\)\s*(?:\(\s*)?[A-Za-z_]\w*\s*[-+](?!>)")
_OFFSET_ALIAS = re.compile(r"\(\s*" + _TYPE + r"\s*\*\s*\)\s*\(\s*(?:u?intptr_t|[us]?int(?:8|16|32|64)_t|"
                           r"u32|s32|unsigned|int|long)\s*\)")                           # (T*)(u32)p
_DOUBLE_CAST = re.compile(r"\(\s*" + _NOT_A_BYTE_PTR + _TYPE + r"\s*\*\s*\)\s*\(\s*\(\s*[A-Za-z_]\w*\s*\*\s*\)")
# (u32*)((u8*)base + 8)

# R13: a virtual slot that exists only to place the ones after it. A real slot with a placeholder name
# (func_80001234, unk_18) is fine: only the word that says "this is padding" is a finding.
_VTABLE_DUMMY = re.compile(r"\bvirtual\b[^;{}]*?(?:_+)?(?:pad(?:ding)?|dummy|filler|reserved|spare|unused)\w*\s*(?=[(;{=])",
                           re.I)
_VTABLE_DUMMY_COMMENT = re.compile(r"\bvirtual\b[^\n]*(?://|/\*)[^\n]*\b(?:pad(?:ding)?|dummy|filler)\b", re.I)

# R17: scaffolding that runs nothing.
_DO_WHILE_ZERO = re.compile(r"\bdo\s*\{\s*\}\s*while\s*\(\s*(?:0|false)\s*\)")
_DEAD_LOOP = re.compile(r"\bwhile\s*\(\s*(?:0|false)\s*\)")
_EMPTY_BLOCK = re.compile(r"^\s*\{\s*\}\s*$")

# R18: assembly, in the forms the project's own sources use. (decomp.wtf already refuses these before a
# function is written; here they are a checked rule on a matched source.)
_INLINE_ASM = re.compile(r"\b(?:__asm__|__asm|asm|_asm)\b\s*(?:volatile\s*)?[\(\{_]")
_ASM_BODY = re.compile(r"\b(?:INCLUDE_ASM|GLOBAL_ASM|INCLUDE_RODATA|\.incbin)\b")
_ASM_INCLUDE = re.compile(r"#\s*include\s*[<\"][^>\"]*\.(?:s|S|asm|bin|inc\.c)[>\"]")

# (rule, pattern, why, run it on the line with its comments)
_CHECKS = [
    ("R4", _OFFSET_DEREF, "an offset cast: a variable's address read as another type, where the real source has a "
                          "typed member", False),
    ("R4", _OFFSET_ADDR, "an offset cast: a variable's address passed on as another type, so a neighbour's bytes are "
                         "read as a member", False),
    ("R4", _OFFSET_BASE, "an offset cast: a pointer cast only to add an offset, where the real source has a member",
     False),
    ("R4", _OFFSET_ALIAS, "pointer/integer aliasing: a pointer rebuilt from an integer to reach the same bytes",
     False),
    ("R4", _DOUBLE_CAST, "an offset cast: a byte pointer cast back to a wider type after an offset, instead of a "
                         "member", False),
    ("R13", _VTABLE_DUMMY, "a dummy or padding virtual slot: a vtable laid out by hand instead of the real slots",
     False),
    ("R13", _VTABLE_DUMMY_COMMENT, "a dummy or padding virtual slot: a vtable laid out by hand instead of the real "
                                   "slots", True),
    ("R17", _DO_WHILE_ZERO, "a do { } while (0) that runs nothing: invented scaffolding to move the score", False),
    ("R17", _DEAD_LOOP, "a loop that can never run: dead code where the real source has a body", False),
    ("R17", _EMPTY_BLOCK, "an empty block: a macro or an inlined helper the compiler made disappear, not written "
                          "out", False),
    ("R18", _INLINE_ASM, "inline assembly: a match that isn't C/C++", False),
    ("R18", _ASM_BODY, "an assembly body (INCLUDE_ASM/GLOBAL_ASM): a match that isn't C/C++", False),
    ("R18", _ASM_INCLUDE, "an assembly include: a match that isn't C/C++", False),
]


def _strip_comments(text: str) -> str:
    """The text with comments blanked out, newlines kept, so a comment about a cast is not a cast and line numbers
    still point at the source."""
    return re.sub(r"/\*.*?\*/|//[^\n]*", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)


def check(source: str) -> list[Finding]:
    """The [match] findings of a source, one per rule and line: empty when it passes R4, R13, R17 and R18.

    shortcut: text, not types — R17 sees the dead-body shapes but not a dummy local (that needs to tell a
    struct member from a local), and a `//` inside a string is read as a comment. Upgrade when a finding is
    ever wrong on real code (the guide's table is the long form of these)."""
    if not source or not source.strip():
        return []
    raw = source.splitlines()
    plain = _strip_comments(source).splitlines()
    found: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for number, (line, bare) in enumerate(zip(raw, plain), 1):
        for rule, pattern, why, with_comments in _CHECKS:
            if (rule, number) in seen:
                continue
            if pattern.search(line if with_comments else bare):
                seen.add((rule, number))
                found.append(Finding(rule, number, line.strip(), why))
    return found


def describe(findings: list[Finding]) -> str:
    """The findings, one per line under the rule they break."""
    return "\n".join(f"- {f.rule} line {f.line}: {f.why}\n    {f.code}" for f in findings)


def verdict(matched: bool, source: str) -> str:
    """The MATCH-PENDING note for a byte-exact source that trips a [match] rule; '' when the bytes didn't match or
    the source passes every rule. Only the label changes: the byte verdict is the caller's and stays its own."""
    if not matched or not (findings := check(source)):
        return ""
    return (f"⚖️ MATCH-PENDING (not matched): the bytes are identical (score 0, banked), but the source trips the "
            f"[match] rules, so this isn't a real match yet. Replace the trick with the real structure and "
            f"compile_and_diff again:\n{describe(findings)}\n(guide(\"rules\") has the table of tricks.)")
