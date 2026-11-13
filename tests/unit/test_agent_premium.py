"""Premium local-agent features: schedule parse, memory, expanded solve topics."""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SYS = str(ROOT / "components" / "assistant")
if SYS not in sys.path:
    sys.path.insert(0, SYS)

import memory  # noqa: E402
import schedule  # noqa: E402
import solve  # noqa: E402
import tools  # noqa: E402


def test_parse_daily_schedule():
    f = schedule.parse_schedule_request("every day at 8am remind me to stretch")
    assert f is not None
    assert f["recur"] == "daily"
    assert f["hour"] == 8
    assert f["minute"] == 0
    assert "stretch" in f["prompt"]
    assert f["kind"] == "notify"


def test_parse_weekday_agent_schedule():
    f = schedule.parse_schedule_request("every weekday at 9 open chrome")
    assert f is not None
    assert f["recur"] == "weekdays"
    assert f["hour"] == 9
    assert f["kind"] == "agent"


def test_route_schedule_and_list():
    r = tools.route("every day at 7:30 am remind me to drink water")
    assert r.actions[0].name == "schedule_add"
    assert r.actions[0].args["hour"] == 7
    assert r.actions[0].args["minute"] == 30
    r2 = tools.route("list scheduled tasks")
    assert r2.actions[0].name == "schedule_list"


def test_memory_roundtrip(tmp_path=None):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "memory.json"
        saved = memory.remember("I prefer Bangla replies", path=path)
        assert "Bangla" in saved
        facts = memory.list_facts(path=path)
        assert any("Bangla" in f for f in facts)
        block = memory.summary_for_prompt(path=path)
        assert "Bangla" in block
        assert memory.forget("bangla", path=path) >= 1


def test_route_remember():
    r = tools.route("remember that my name is Imran")
    assert r.actions[0].name == "memory_remember"
    assert "Imran" in r.actions[0].args["fact"]


def test_solve_topics_expanded():
    assert solve.topic_of("no sound from speakers") == "audio"
    assert solve.topic_of("bluetooth will not pair") == "bluetooth"
    assert solve.topic_of("printer not working") == "printer"
    assert solve.wants_solve("wifi is not working")
    assert solve.wants_solve("no sound")
