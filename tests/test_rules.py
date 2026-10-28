"""The [match] rules: score 0 built with a trick is MATCH-PENDING, not matched (R4, R13, R17, R18).

guide("rules") lists the tricks; these check them on the source of a function whose bytes already agree. A
finding never changes the bytes — it only stops a contrived source from being called a real match, and every
finding names its rule and line. The guardrail fixtures below are real code that has to PASS.
"""

import json
from types import SimpleNamespace

import pytest

from decompnet import scoring
from decompnet.app.engine import RomNetwork
from decompnet.forks import rules

# ---------------------------------------------------------------- the fakematches (flagged)

# R4: a member read through its neighbour's address
OFFSET_CAST = """\
u32 entry_head(Player *p) {
    return *(u32*)&p->state;
}
"""

# R4: the same trick through a byte pointer
OFFSET_BASE = """\
u32 entry_value(void *base) {
    return *(u32*)((u8*)base + 8);
}
"""

# R13: a vtable laid out with padding slots
DUMMY_VTABLE = """\
class Actor {
public:
    virtual ~Actor();
    virtual void pad0();
    virtual void pad4();  /* padding so the layout matches */
    virtual void update();
};
"""

# R17: scaffolding that runs nothing
DEAD_CODE = """\
void actor_tick(Actor *a) {
    do { } while (0);
    a->ticks++;
}
"""

# R18: a match that isn't C
INLINE_ASM = """\
u32 read_cop0(void) {
    __asm__ volatile("mfc0 $v0, $12");
    return 0;
}
"""

# ---------------------------------------------------------------- real code (must pass)

# a member, typed and named
CLEAN = """\
u32 read_state(Player *p) {
    return p->state;
}
"""

# buffer walking through byte pointers is what the original wrote
BYTE_WALK = """\
void fill(u8 *dst, u8 value, s32 n) {
    u8 *src = dst + 1;
    for (s32 i = 0; i < n; i++) {
        *(u8*)((u8*)dst + i) = value;
    }
}
"""

# hardware: the volatile is the register, not a carrier
HW_VOLATILE = """\
u32 wait_for_dma(volatile u32 *status) {
    while ((*status & DMA_BUSY) != 0) {
    }
    return *status;
}
"""

# padding the layout needs is not fake code
STRUCT_PADDING = """\
typedef struct {
    u8 type;
    u8 pad[3];
    u32 value;
} Entry;
"""

# placeholder names on real vtable slots
PLACEHOLDER_VTABLE = """\
class Actor {
public:
    virtual ~Actor();
    virtual void func_80001234();
    virtual void unk_18();
    virtual void D_8012AB00();
};
"""

# the line info the compiler forces
LINE_INFO = """\
const char *where(void) {
    return __FILE__ ":";
}
"""

# the era's own idioms
ERA_IDIOMS = """\
s32 sum(const u8 *p, s32 n) {
    s32 total = 0;
    while (n-- > 0) {
        total += *p++;
    }
    return total;
}
"""

# a plain downcast of a base pointer is not an offset cast
DOWNCAST = """\
u32 window_size(GzState *gz) {
    return ((deflate_state *)gz->state)->window_size;
}
"""

FLAGGED = [(OFFSET_CAST, "R4"), (OFFSET_BASE, "R4"), (DUMMY_VTABLE, "R13"), (DEAD_CODE, "R17"), (INLINE_ASM, "R18")]
CLEAN_SOURCES = [CLEAN, BYTE_WALK, HW_VOLATILE, STRUCT_PADDING, PLACEHOLDER_VTABLE, LINE_INFO, ERA_IDIOMS, DOWNCAST]


@pytest.mark.parametrize("source,rule", FLAGGED)
def test_a_fakematch_names_its_rule_and_line(source, rule):
    found = rules.check(source)
    assert {f.rule for f in found} == {rule}, found
    assert 1 <= found[0].line <= len(source.splitlines()) and found[0].code and found[0].why


@pytest.mark.parametrize("source", CLEAN_SOURCES)
def test_real_code_passes_every_rule(source):
    assert rules.check(source) == []


def test_the_verdict_only_moves_on_a_byte_exact_source():
    assert rules.verdict(False, OFFSET_CAST) == ""       # bytes didn't match: the byte judge says what happens
    assert rules.verdict(True, CLEAN) == ""              # bytes matched and the source is real: matched
    pending = rules.verdict(True, OFFSET_CAST)
    assert pending.startswith("⚖️ MATCH-PENDING") and "R4 line 2" in pending
    assert "return *(u32*)&p->state;" in pending


# ---------------------------------------------------------------- the gate on a score-0 result


def _byte_exact(tmp_path, monkeypatch, bytes_match=True):
    """A project whose judge is stubbed to call every attempt byte-exact: everything but the compiler and objdiff is
    the real code path (the toolchain and objdiff-cli aren't installed on a test machine)."""
    net = RomNetwork(tmp_path / "app.db", tmp_path / "ws")
    (tmp_path / "ws").mkdir(exist_ok=True)
    with net.store.tx() as db:
        pid = db.execute("INSERT INTO projects(slug,name,description,arch,big_endian,root,config) "
                         "VALUES(?,?,?,?,?,?,?)",
                         ("game", "Game", "", "mips", 1, str(tmp_path), json.dumps({"kind": "rom"}))).lastrowid
        db.execute("INSERT INTO context_versions(project_id,version,header,agent_id,message,created_at,unit) "
                   "VALUES(?,?,?,?,?,?,?)", (pid, 1, "", None, "", 0.0, ""))
        for name in ("entry_head", "read_state"):
            db.execute("INSERT INTO functions(project_id,name,size,n_insns,target,relocs,asm,status,unit) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (pid, name, 16, 4, b"\0" * 16, "[]", "", "open", ""))
    monkeypatch.setattr(net, "_compile", lambda proj, header, source: SimpleNamespace(ok=True, log="", obj=b""))
    monkeypatch.setattr(net, "_evaluate", lambda fn, proj, obj: (object(), None, []))
    monkeypatch.setattr(scoring, "diff", lambda target, cand: scoring.DiffResult(0 if bytes_match else 4, 100, [], bytes_match))
    monkeypatch.setattr(net, "on_match", lambda proj, fid, agent=None: None)  # (twins would compile for real)
    agent, _ = net.local_agent("claude-1")
    return net, agent


def test_a_byte_exact_fakematch_is_match_pending_with_its_rule_and_line(tmp_path, monkeypatch):
    net, agent = _byte_exact(tmp_path, monkeypatch)
    res = net.attempt(agent, "entry_head", OFFSET_CAST)
    assert res["score"] == 0 and res["match_pending"]     # the bytes are banked: the judge is untouched
    assert res["text"].startswith("⚖️ MATCH-PENDING") and "R4 line 2" in res["text"]
    assert "✅ MATCH!" not in res["text"]
    # the byte verdict stands in the database; only the label on a byte-exact source changed
    assert net.store.one("SELECT status, best_score FROM functions WHERE name='entry_head'")["status"] == "matched"
    assert net.rule_check("entry_head").startswith("⚖️ entry_head trips the [match] rules")
    assert "R4 line 2" in net.rule_check("entry_head")


def test_a_clean_byte_exact_function_is_still_matched(tmp_path, monkeypatch):
    net, agent = _byte_exact(tmp_path, monkeypatch)
    res = net.attempt(agent, "read_state", CLEAN)
    assert res == {**res, "score": 0, "matched": True} and "match_pending" not in res
    assert res["text"].startswith("✅ MATCH!") and "MATCH-PENDING" not in res["text"]
    assert net.rule_check("read_state").startswith("✅ read_state passes the [match] rules")


def test_the_gate_never_touches_a_near_miss(tmp_path, monkeypatch):
    """The checker only relabels a byte-exact source: a 4-instruction diff is reported by the byte judge as it
    always was, fakematch or not."""
    net, agent = _byte_exact(tmp_path, monkeypatch, bytes_match=False)
    res = net.attempt(agent, "entry_head", OFFSET_CAST)
    assert res["score"] == 4 and not res["matched"]
    assert "MATCH-PENDING" not in res["text"] and res["text"].startswith("score 4")
