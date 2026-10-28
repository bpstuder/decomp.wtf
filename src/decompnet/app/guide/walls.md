# Classifying a wall

A pinned compiler is deterministic: the bytes come from one exact input (the preprocessed source and the
flags). Retail came out of the same compiler, so every function is reproducible in principle — a miss
means some input is wrong, and your job is to find which one. Classify the wall before fighting it, in
this order, and don't move to the next class until the one before it is flat:

| the diff shows… | the cause is… | fix it by… |
|---|---|---|
| the CALL set differs (a callee missing, extra, or at a different site) | the body is incomplete, the inline boundary is wrong, or a call tail is duplicated | finishing or inline reconstruction — source work, not permutation |
| block, branch or return counts differ | control flow differs | a real source construct (separate returns, `goto`, `&&`/`||` collapse, a loop form) — source work |
| counts agree but operand order, spills or registers differ | register allocation / scheduling | the source-shape checklist, then the machine draft's levers |
| the masked diff is identical but it still won't reach 0 | a referent: a wrong name, offset, symbol or data value | labelling / data work — never permutation |

The two mistakes that waste the most effort:
- Permuting a referent or control-flow wall. If the masked bytes agree but the score is below 0, or a
  call or branch count differs, no register reshuffle will close it. Fix the name, offset, call or branch.
- Calling it "register allocation" while a call is still missing or a block is still merged. Confirm the
  call multiset and the block/branch counts are identical before you treat the residue as schedulable.

Know the compiler's inline policy first (which functions it expands, the per-caller budget, whether
templates expand without `inline`): a call-count delta is usually an inline decision, not a missing body.
A callee on both sides at a different count can be a per-site inline choice *or* a duplicated exit tail
that carries the call — locate the sites before you pick a lever.

When the residue really is register/schedule (same calls, same skeleton, only order or spills differ), the
m2c/Ghidra draft already tried the obvious reshuffles. `compile_and_diff` a *sourced* change — a
corrected type, a moved declaration, a recovered local — not a hand-tuned register order. A flat score
after that is a candidate to release with notes (`similarity`), not to grind.
