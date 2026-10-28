# What counts as a match

Score 0 means the bytes are identical. It is not the same as a real match. The point of a decompilation
is source a person can read and change; a byte-exact function built with a trick is not that. Before you
declare a function matched, it has to pass both:

1. **The bytes** — score 0.
2. **The reader test** — would a programmer on the original team, writing in this codebase's style, have
   typed this? If you wrote a contrivance to move the score, it fails the test even at score 0.

The byte-exact-but-fake ones are the ones to catch. Each of these produces the right bytes and is a clue
to where the real source differs, not a closure:

| if it only matches with… | the real source probably has… |
|---|---|
| an offset cast (`*(u32*)&x`, `(T*)base + n`) | a typed member, or a declared type you haven't modelled |
| a `volatile`, or a dummy / uninitialised local | a real local, a wider type, or an aliasing pointer |
| an empty block, `{ }`, or a `do { } while (0)` | a macro, or a helper the compiler inlined |
| a variable reused for two unrelated values | two locals that were merged into one |
| inline asm or an asm function | — (not allowed here anyway; write the C) |

What to do instead, before you call it matched:
- Model real types: a member, not an offset; a typed pointer, not `void *`; one local per meaning, named
  for it; a named constant, not a bare number.
- Keep the era's genuine idioms — `*p++`, `goto fail`, a bug the original shipped. Those are real code,
  not tricks. The line is simple: an idiom the original would have written passes; a contrivance you
  invented only to move the score doesn't.

When the bytes genuinely need a form that breaks the project's *style* (not its matching rules), keep the
bytes and leave a short comment saying why — a style exception, not fake code. When the form is fake code,
it is not a match: keep reconstructing, or `release_function` it with a note that it is byte-exact but the
source is fake — the next agent needs to know the bytes are banked and the source isn't.

Naming is open work, not a blocker: a placeholder name (`func_80…`, `unk_0x…`, `D_801…`) is fine to bank
the bytes; a confident invented name is not. Share real names you do find with `rename_symbol`.
