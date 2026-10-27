"""Helper agents: each CLI's output read into the live feed (Antigravity CLI, opencode errors), prompts sent on
stdin, `decomp connect`, and the compact context agents get (assembly, diffs)."""

import json
import time

import httpx
import pytest

from decompnet import scoring
from decompnet.app import agents, connect


def test_antigravity_stream_json_is_read():
    state: dict = {}
    lines = [
        {"event": "init", "conversation_id": "c", "init": {"cwd": "/w", "tools": ["call_mcp_tool"]}},
        {"event": "step_update", "step_update": {"step_index": 1, "state": "ACTIVE", "step_type": "agent_response",
                                                 "text_delta": "Claiming "}},
        {"event": "step_update", "step_update": {"step_index": 1, "state": "ACTIVE", "step_type": "agent_response",
                                                 "text_delta": "the next one."}},
        {"event": "step_update", "step_update": {"step_index": 1, "state": "DONE", "step_type": "agent_response",
                                                 "text_delta": "\n"}},
        {"event": "step_update", "step_update": {"step_index": 2, "state": "ACTIVE", "step_type": "tool",
                                                 "tool_name": "call_mcp_tool", "tool_info": {"name": "call_mcp_tool",
                                                 "parameters": {"ServerName": "decomp", "ToolName": "claim_function",
                                                                "Arguments": {"strategy": "easiest"}}}}},
        {"event": "step_update", "step_update": {"step_index": 2, "state": "DONE", "step_type": "tool",
                                                 "tool_name": "call_mcp_tool", "tool_info": {"name": "call_mcp_tool",
                                                 "parameters": {"ServerName": "decomp", "ToolName": "claim_function",
                                                                "Arguments": {"strategy": "easiest"}}}}},
        {"event": "result", "result": {"status": "SUCCESS", "num_turns": 3, "usage": {"total_tokens": 1200}}},
    ]
    out = [item for line in lines for item in agents.parse_line("antigravity", json.dumps(line), state)]
    assert out == [("text", "Claiming the next one."), ("tool", "claim_function(easiest)"),
                   ("usage", json.dumps({"tokens": 1200})), ("info", "session finished (3 turns)")]


def test_antigravity_refusing_decomps_tools_says_how_to_allow_them():
    line = json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "",
                                                     "denied_actions": [{"action": "mcp", "display_name": "CallMcpTool"}]}})
    errors = [t for k, t in agents.parse_line("antigravity", line, {}) if k == "error"]
    assert errors and errors[0].startswith("Antigravity refused") and agents.AGY_ALLOW in errors[0]


def test_opencode_errors_say_what_failed():
    """Issue #3: opencode's error event nests the message under data; the feed showed "None"."""
    line = json.dumps({"type": "error", "sessionID": "s", "error": {"name": "ProviderAuthError",
                                                                    "data": {"message": "no key for deepseek"}}})
    assert agents.parse_line("opencode", line) == [("error", "ProviderAuthError: no key for deepseek")]
    generic = json.dumps({"type": "error", "error": {"name": "UnknownError", "data": {"message": "Unexpected server error."}}})
    assert agents.parse_line("opencode", generic) == []  # a placeholder: the log line on stderr says what failed
    assert agents.parse_line("codex", json.dumps({"type": "turn.failed", "error": {"message": "quota"}})) == [("error", "quota")]
    log = ('timestamp=2026-10-14T14:25:35.946Z level=ERROR run=89d82ac2 message=failed ref=err_ab91f09e '
           'error="ProviderModelNotFoundError: Model not found: nosuch/model." cause="ProviderModelNotFoundError: x\\n at y"')
    assert agents.clean_stderr("opencode", log) == "ProviderModelNotFoundError: Model not found: nosuch/model."
    assert agents.clean_stderr("opencode", "timestamp=1 level=WARN message=slow") == ""
    agy = 'AGY_ERROR: {"message": "quota exhausted", "code": 429}'
    assert agents.clean_stderr("antigravity", agy) == "quota exhausted"


def _manager(tmp_path, monkeypatch, kind):
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / {"claude": "claude", "codex": "codex", "antigravity": "agy", "opencode": "opencode"}[kind]
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(agents, "_which", lambda cmd: str(exe))
    m = agents.Manager.__new__(agents.Manager)
    m.mcp_url = "http://127.0.0.1:6464/mcp"
    m.prompt = lambda s: "line one\nline two with \"quotes\" & <ampersands>"
    return m


def test_prompts_go_in_on_stdin_never_the_command_line(tmp_path, monkeypatch):
    """On Windows, npm installs agents as .cmd scripts: cmd.exe cuts a multi-line argument at its first line break
    and caps the command line at 8191 characters."""
    for kind in ("claude", "codex", "antigravity", "opencode"):
        m = _manager(tmp_path, monkeypatch, kind)
        s = agents.Session(f"{kind}-1", kind, kind, "demo", f"{kind}-1", {"model": "some-model"})
        work = tmp_path / kind
        work.mkdir()
        cmd, env, stdin = m._command(s, "tok", work)
        assert not any("line one" in a for a in cmd), (kind, cmd)
        assert "line one" in stdin and "some-model" in cmd
        assert env["DECOMP_SESSION_TOKEN"] == "tok"  # a `decomp mcp` the agent starts works as this session
    # Antigravity: one stream-json user message, the server in the workspace's own MCP config
    m = _manager(tmp_path, monkeypatch, "antigravity")
    s = agents.Session("antigravity-2", "antigravity", "a", "demo", "antigravity-2", {})
    (tmp_path / "agy2").mkdir()
    cmd, _, stdin = m._command(s, "tok", tmp_path / "agy2")
    assert json.loads(stdin) == {"event": "user", "message": {"content": "line one\nline two with \"quotes\" & <ampersands>"}}
    assert cmd[1:5] == ["--output-format", "stream-json", "--input-format", "stream-json"]
    cfg = json.loads((tmp_path / "agy2" / ".agents" / "mcp_config.json").read_text())
    assert cfg["mcpServers"]["decomp"] == {"serverUrl": "http://127.0.0.1:6464/mcp",
                                           "headers": {"Authorization": "Bearer tok"}}


def test_opencode_free_models_keep_their_tools_but_never_get_to_use_them(tmp_path, monkeypatch):
    """OpenCode Zen's free models refuse requests whose tools were taken out ("deny"); "ask" keeps them listed and
    `opencode run` rejects every ask. Models of other providers get "deny"."""
    monkeypatch.setattr(agents, "_config_model", lambda kind: None)
    for model, rule in (("opencode/big-pickle", "ask"), ("", "ask"), ("deepseek/deepseek-chat", "deny")):
        m = _manager(tmp_path, monkeypatch, "opencode")
        s = agents.Session("opencode-1", "opencode", "o", "demo", "opencode-1", {"model": model})
        work = tmp_path / f"oc-{rule}-{model.replace('/', '_')}"
        work.mkdir()
        m._command(s, "tok", work)
        assert json.loads((work / "opencode.json").read_text())["permission"] == {"edit": rule, "bash": rule, "webfetch": rule}


def test_gemini_cli_helpers_carry_on_as_antigravity():
    assert agents.kind_id("gemini") == "antigravity" and agents.kind_id("agy") == "antigravity"
    assert "gemini" not in agents.KINDS and agents.KINDS["antigravity"].command == "agy"


def test_connect_antigravity(tmp_path, monkeypatch):
    monkeypatch.setattr(connect, "_which", lambda cmd: f"/bin/{cmd}")
    monkeypatch.setattr(connect, "bridge_command", lambda: ["/usr/bin/python3", "-m", "decompnet.app.cli", "mcp"])
    cmd = connect.commands("antigravity")
    # agy wants flags before the name, and `--` before a command whose arguments start with "-"
    assert cmd == ["/bin/agy", "mcp", "add", "-e", "DECOMP_AGENT_NAME=antigravity", "decomp", "--",
                   "/usr/bin/python3", "-m", "decompnet.app.cli", "mcp"]


def test_assembly_for_agents_is_compact():
    asm = ("glabel func_80013C60\n/* 4460 80013C60 27BDFF88 */  addiu      $sp, $sp, -0x78\n"
           "/* 4464 80013C64 AFB10054 */  sw         $s1, 0x54($sp)\n.L80013CC4:\n"
           "/* 44C8 80013CC8 00000000 */  nop\n")
    assert scoring.compact_asm(asm) == ("glabel func_80013C60\n  addiu $sp, $sp, -0x78\n  sw $s1, 0x54($sp)\n"
                                        ".L80013CC4:\n  nop")
    assert scoring.compact_asm("\tpush {r4, lr}\n") == "\tpush {r4, lr}"  # other listings stay as they are


def test_diffs_sum_up_and_shorten_long_runs():
    rows = [(" ", "addiu $sp, $sp, -8", "addiu $sp, $sp, -8"), ("r", "move $s0, $a0", "move $s1, $a0")]
    rows += [("<", f"lw $v0, {i}($s0)", "") for i in range(300)]
    rows += [(" ", "jr $ra", "jr $ra")]
    text = scoring.render_rows(rows)
    assert text.splitlines()[0] == "300 missing, 1 regalloc"
    assert "... 297 more missing (target only) ..." in text and "lw $v0, 299($s0)" in text
    assert len(text.splitlines()) < 15


def test_helpers_and_the_agent_you_talk_to_never_share_an_identity(tmp_path):
    """8 Antigravity helpers showed as 15 agents: the helpers reached decomp.wtf through the user's own `decomp mcp`,
    which signed each in as a new agent of the user's, named like the helpers (antigravity-9...). Chat identities
    are numbered differently now, and a helper never counts as the agent the user talks to."""
    from decompnet.app.engine import RomNetwork

    net = RomNetwork(tmp_path / "app.db", tmp_path)
    a, _ = net.chat_agent("antigravity")
    b, _ = net.chat_agent("antigravity")  # a second chat session at the same time
    assert (a.name, b.name) == ("antigravity", "antigravity_2")
    net.register_agent("antigravity-2", "you", origin="chat")  # a chat identity from before, named like a helper
    helper, _ = net.local_agent("antigravity-2")
    assert not net.is_chat(helper) and net.is_chat(a)
    assert net.local_agent("autopilot")[0].name == "autopilot"


def test_antigravity_helpers_say_when_it_isnt_connected(tmp_path, monkeypatch):
    from decompnet.app import connect

    m = _manager(tmp_path, monkeypatch, "antigravity")
    monkeypatch.setattr(connect, "status", lambda kind: False)
    s = agents.Session("antigravity-1", "antigravity", "a", "demo", "antigravity-1", {})
    s.runs = 1
    with pytest.raises(agents.Fatal, match="decomp connect antigravity"):
        m._run_cli(s, "tok", tmp_path)


def test_a_dead_model_stream_ends_the_run_instead_of_hanging(tmp_path, monkeypatch):
    """OpenCode Zen's free models answer "stream error: AI_APICallError: Rate limit exceeded" and then wait for an
    answer that never comes: the session sat there looking busy - holding the functions it had claimed - for as long
    as it was left alone. The run is stopped and reported, and marked throttled so `_run` waits the limit out."""
    monkeypatch.setattr(agents, "STREAM_DEAD_SECONDS", 1.0)
    monkeypatch.setattr(agents, "STALL_SECONDS", 3600.0)  # only the failed-stream watch may fire here
    m = _manager(tmp_path, monkeypatch, "opencode")
    exe = tmp_path / "bin" / "opencode"
    exe.write_text("#!/bin/sh\n"
                   "echo 'timestamp=2026-10-17T08:20:27.105Z level=ERROR run=1 message=\"stream error\" "
                   "providerID=opencode modelID=beam-free error=\"AI_APICallError: Rate limit exceeded. "
                   "Please try again later.\"' >&2\n"
                   "exec sleep 600\n")
    exe.chmod(0o755)
    s = agents.Session("opencode-1", "opencode", "o", "demo", "opencode-1", {"model": "opencode/beam-free"})
    work = tmp_path / "w"
    work.mkdir()
    t0 = time.monotonic()
    assert m._run_cli(s, "tok", work) is False
    assert time.monotonic() - t0 < 30  # stopped by the watch, not by the CLI's own 600s sleep
    assert s.proc is None and s.throttled is True
    assert any("no answer for" in f["text"] and "Rate limit exceeded" in f["text"] for f in s.feed)


def test_a_run_that_says_nothing_at_all_is_stopped_too(tmp_path, monkeypatch):
    """A CLI that hangs without reporting anything is the same problem: it is not left holding claims either."""
    monkeypatch.setattr(agents, "STALL_SECONDS", 1.0)
    m = _manager(tmp_path, monkeypatch, "opencode")
    exe = tmp_path / "bin" / "opencode"
    exe.write_text("#!/bin/sh\nexec sleep 600\n")
    exe.chmod(0o755)
    s = agents.Session("opencode-1", "opencode", "o", "demo", "opencode-1", {})
    work = tmp_path / "w2"
    work.mkdir()
    assert m._run_cli(s, "tok", work) is False
    assert s.throttled is False and s.error.startswith("the run stalled: nothing from the agent for")


def test_the_stall_watches_are_thresholds_not_a_short_fuse():
    """A long generation or a slow compile must survive them: the grace periods are minutes, not seconds."""
    assert agents.STALL_SECONDS >= 600 and agents.STREAM_DEAD_SECONDS >= 60
    assert agents.stall_reason(60, "", agents.STALL_SECONDS, agents.STREAM_DEAD_SECONDS) == ""
    assert agents.stall_reason(120, "AI_APICallError: Rate limit exceeded.", 900.0, 120.0) == ""
    assert agents.stall_reason(1800, "", 900.0, 120.0) == "nothing from the agent for 30 min"
    assert agents.stall_reason(1800, "AI_APICallError: Rate limit exceeded.", 900.0, 120.0) == (
        "no answer for 30 min after the model's stream failed (AI_APICallError: Rate limit exceeded.)")


def test_the_hourly_token_bucket_is_counted_per_key_and_ages_out():
    """A provider caps tokens an hour per key and counts every model on it into the same bucket (Nous' free tier:
    6M an hour), so the count is per endpoint, not per session, and a full hour means waiting - not a 429."""
    tokens = agents.HourlyTokens()
    tokens.spend("e1", 800, now=0)
    assert tokens.wait_seconds("e1", 1000, 100, now=10) == 0  # 800 + 100 still fits
    assert tokens.wait_seconds("e1", 1000, 300, now=10) == 3590  # the 800 has to age out first
    assert tokens.wait_seconds("e2", 1000, 300, now=10) == 0  # another endpoint: another key, another bucket
    tokens.spend("e1", 900, now=3601)  # an hour later the first spend has left the window
    assert tokens.used("e1", now=3602) == 900
    assert tokens.wait_seconds("e1", 1000, 300, now=3602) == 3599
    assert tokens.wait_seconds("e1", 500, 900, now=3602) == 3599  # a request over the whole limit waits for empty
    assert tokens.wait_seconds("e2", 0, 1, now=3602) == 0  # no limit: never wait


def test_a_spent_hour_pauses_the_builtin_agent_instead_of_hitting_the_provider(tmp_path, monkeypatch):
    """With a tokens-an-hour limit on the endpoint, the loop waits for room instead of sending the request that would
    earn a 429, and says why in the feed."""
    m = agents.Manager(None, tmp_path, "http://127.0.0.1:9/mcp")
    m.net = type("Net", (), {"fork_slug": lambda self, slug: None, "add_spend": lambda self, *a: None})()
    m.prompt = lambda s: "go"
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        msg = {"role": "assistant", "content": "looking", "tool_calls": [
            {"id": str(len(sent)), "type": "function", "function": {"name": "list_functions", "arguments": "{}"}}]}
        return httpx.Response(200, json={"choices": [{"message": msg}], "usage": {"total_tokens": 900}})

    real = httpx.Client
    monkeypatch.setattr(agents.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(agents, "api_tool_schemas", lambda fork=False: [])
    monkeypatch.setattr(agents.tools, "call", lambda *a: "no functions yet")
    s = agents.Session("api-h", "api", "Test", "demo", "api-hourly",
                       {"endpoint": "e-hourly", "base_url": "http://mock/v1", "model": "m",
                        "context_tokens": 32768, "tokens_per_hour": 1000})
    waits = []
    monkeypatch.setattr(s.stop, "wait", lambda secs=None: (waits.append(secs), s.stop.set())[1])
    assert m._run_api(s, None) is True  # stopped by the wait, not by an error
    assert len(sent) == 1 and m.hourly.used("e-hourly") == 900
    assert waits and waits[0] > 3000  # the bucket is spent: the next request waits for it to age out
    assert any("tokens an hour" in f["text"] for f in s.feed)
