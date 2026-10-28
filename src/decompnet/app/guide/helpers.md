# Restoring inlined helpers

The original authors wrote accessors and small inline helpers, and the compiler expanded them into the
caller. A reconstruction that transcribes the expanded body can read fine and still be wrong: it misses
the helper's own boundaries, scopes and evaluation order, and that is often exactly what a stubborn wall
is. Restoring the helper is correct source whether or not the score moves, and once enough are restored
the hard functions start to close.

Spot one — a statement working below the abstraction level of the code around it:
- **Another class's internals** — indexing a member array, walking a list, testing another object's flag
  bits. The owner had an accessor (`GetAt`, `IsAlive`, `HasFlag`).
- **The same expression twice** — the same field path or computation written twice instead of held in a
  local. The original called the helper at each site; a transcriber would have cached it.
- **A scoped block** — `{ … }` with its own locals mid-function: an inlined helper body or a macro.
- **A cast at a call site** — `SkillId(m_skill)` shows the helper's typed parameter.

Prove it before you write it (a helper needs evidence, not taste):
- Repetition is the strongest signal — search the source (`search_code` in a fork; the shared header
  otherwise) and count the sites. The same pattern at several sites, especially in different classes, is
  a helper.
- Check the owning class and its headers first: it may already exist, unused, or for a sibling field.
- Surviving source (SDKs, the engine lineage, a matched look-alike from `find_similar`) gives the name
  and signature.

Apply it everywhere and measure:
1. Replace every site, not just the one you found it in.
2. `compile_and_diff` the batch and read the score changes.
3. An exact function must stay exact after the rewrite. If it drops, the helper's shape is wrong
   somewhere (by value vs by reference, `const`, parameter type, a statement split) — fix the shape, don't
   abandon the helper.
4. Commit one helper at a time: the helper and all its sites.

Don't invent helpers without repetition or retail evidence, and never add one just to move a score.
