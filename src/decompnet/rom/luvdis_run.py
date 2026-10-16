"""Runs luvdis (in its own environment: `python luvdis_run.py disasm ...`) with the fixes luvdis's emulation needs.

Standard library only: this runs in luvdis's environment, not decomp.wtf's.

luvdis finds the functions and decides how each one ends by emulating it. Two things it models wrongly
each ended a whole ROM's disassembly, and both are patched here rather than upstream (luvdis is pinned
by commit, and its repository has moved on to packaging changes, not fixes):

- Code that pops more than it pushed (a function entered past its own push, or a guess that isn't a
  function) takes its stack index below zero, and the next push then writes outside the list:
  "IndexError: list assignment index out of range" destroyed the disassembly of Spyro: Attack of the
  Rhynocs. A push below the start now stores nothing, as a load from there already reads "unknown".

- A Thumb-2 instruction has no `rd` field, and luvdis's exit analysis assumed one, so it died with
  "AttributeError: 'Thumb20' object has no attribute 'rd'" on Shaman King: Master of Spirits — after
  644 functions were already found, in the second pass over code nothing calls. luvdis classifies
  GBATEK THUMB.19 (a partial `bl`, `PC = LR + imm<<1`) that way. An instruction whose operands can't
  be read is now an unknown exit, which is what the same code already means by `None`: neither a
  proper return nor a misbehaviour. Both outcomes feed luvdis's verdict, so neither is assumed, and
  the runtime range still ends after the instruction, so nothing downstream loses its place.

Each replacement has to match the pinned luvdis source exactly, once. A version change that moved the
code would otherwise leave the tool unpatched while everything else keeps working, so this reports it
and stops — a one-edit fix, instead of failing inside someone's import.
"""

import importlib.util
import sys

# (what the pinned luvdis has, what it should have, what it costs when it goes wrong)
FIXES = [
    ("""                        if self.sp >= len(self.stack):
                            self.stack.append(value)
                        else:
                            self.stack[self.sp] = value
""",
     """                        if self.sp >= len(self.stack):
                            self.stack.append(value)
                        elif self.sp >= 0:
                            self.stack[self.sp] = value
""",
     "a push below the stack's start (code that pops more than it pushed)"),
    ("""                    else:  # ADD/MOV pc
                        target = state[ins.rd] & 0xffffffff
""",
     """                    elif not hasattr(ins, "rd"):  # a Thumb-2 instruction: no register operand to read
                        end = ins.address + ins.size  # the next instruction, whatever it is
                        exit_behaved = None  # an unknown exit, not a crash and not a guess
                        break
                    else:  # ADD/MOV pc
                        target = state[ins.rd] & 0xffffffff
""",
     "a Thumb-2 instruction in the exit analysis (no `rd` to read)"),
]


def patched(source: str, origin: str) -> str:
    """`source` with every fix applied, each of which must match exactly once."""
    for has, should, what in FIXES:
        if source.count(has) != 1:
            raise SystemExit(
                f"luvdis_run: {origin} no longer contains {what}: the pinned luvdis changed, so that fix "
                "is not being applied. Update the FIXES in luvdis_run.py to match it.")
        source = source.replace(has, should, 1)
    return source


def main() -> int:
    spec = importlib.util.find_spec("luvdis.analyze")
    if spec is None or not spec.origin:
        raise SystemExit("luvdis_run: luvdis.analyze isn't in this environment: install luvdis first")
    origin = spec.origin
    with open(origin, encoding="utf-8") as f:
        source = f.read()
    module = importlib.util.module_from_spec(spec)
    sys.modules["luvdis.analyze"] = module
    exec(compile(patched(source, origin), origin, "exec"), module.__dict__)
    from luvdis.__main__ import main as luvdis

    return luvdis(prog_name="luvdis")


if __name__ == "__main__":
    sys.exit(main())
