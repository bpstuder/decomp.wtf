# Reconstructing a hard function

`workflow` is the loop; this is how to work a hard function well inside it. Small functions mostly match
on the first try — save this for the ones that don't.

## Evidence pass, before you edit
Gather before writing, with the tools:
- The gap: the first divergence, both sides' assembly, and the diff's tags (`workflow`, "Reading the
  diff").
- Operands: constant, FP-op and *ordered relocation-target* differences.
- Switches: if there is one, the case-to-arm mapping against the ROM's tables (a permuted table scores
  near-exact, so a real mismatch here is a real bug).
- Context: callers and callees, the vtable slot, the class and its siblings.
- Naming evidence the binary carries itself: error/log strings that begin with a function name, command
  or cvar strings, assert text. Start from those for names.
- A look-alike: `find_similar` — a matched near-copy is the fastest route in.

Read the whole function, its declaration, its callers and callees, and any matched neighbour before you
call a difference "compiler residue". The m2c/Ghidra draft's variable merges, casts and placeholder names
are what you are removing, not the source.

## Reconstruct, then compare
Rank what you try, cheapest and most-evidenced first:
1. a matched look-alike's source, and the whole function family;
2. a wrong identity, ABI, type, layout or referent, or a missing body;
3. a real inline boundary, helper, macro or operator you have proven;
4. local count, scope, lifetime and evaluation order;
5. expression shape, loops, library idioms;
6. compiler-state experiments — only after all of the above are credible.

Write every candidate as the original author would have: typed members not offsets, one named local per
meaning, named constants. A candidate that only matches through a trick (see `rules`) is not an answer —
read it as a pointer to what is really missing and go there.

## Recover lifetimes before blaming the register allocator
A frame-size or register difference is usually a missing value, not allocation. Before you call it
schedule residue:
- Map each stack slot to a real value — an aggregate home, a scalar spill, a reused argument slot, a
  hidden return buffer. A frame-size difference alone doesn't identify the cause.
- Trace each value from creation to last use across calls and branches: declaration vs assignment,
  sibling vs nested scopes, storage owned by the caller or by an inlined helper.
- Check the boundaries: by-value args are evaluated before a helper body while references can defer loads
  to their use; a returned aggregate, a void out-param and a helper returning a reference are three
  different controls — test them as separate changes.

## Finish the source
When the score hits 0:
1. Share what you learned so other agents benefit (`workflow`, step 5): prototypes/structs ->
   `edit_context`, real names -> `rename_symbol`, quirks -> `add_note`.
2. Read the function once against the reader test (`rules`): a merged variable, a confident invented name,
   a helper hidden behind a repeated expression, a shipped bug that isn't labelled.
3. Add the free, byte-safe finishing: names from evidence (placeholders where nothing is known), named
   constants, the project's braces and layout. In a fork project the file must still link after this.

Report per function what you closed, what you released with, and what is still open. Don't grind past the
effort cap (`similarity`).
