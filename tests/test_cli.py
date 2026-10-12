from pathlib import Path

import pytest
from busylib import types
from busylib.exceptions import BusyBarAPIError

from busybar_calendar import cli, connect, diagnose
from busybar_calendar.config import CONFIG_ENV, Config, ConfigError, find

SOURCES = {"sources": [{"name": "Feed", "type": "ics", "url": "https://x"}]}


def test_find_prefers_flag_then_env_then_cwd_then_config_dir(tmp_path, monkeypatch):
    home = tmp_path / "xdg"
    (home / "busybar-calendar").mkdir(parents=True)
    in_home = home / "busybar-calendar" / "config.toml"
    in_home.write_text("")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)

    assert find() == in_home
    (tmp_path / "config.toml").write_text("")
    assert find() == Path("config.toml")
    monkeypatch.setenv(CONFIG_ENV, "/elsewhere.toml")
    assert find() == Path("/elsewhere.toml")
    assert find("given.toml") == Path("given.toml")


def test_find_says_where_it_looked(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "none"))
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="busybar-calendar init"):
        find()


class FakeBar:
    def __init__(self, refuse=None, mode="disabled"):
        self.refuse, self.mode = refuse, mode

    async def version(self):
        return types.VersionInfo(api_semver="27.5.0")

    async def status_firmware(self):
        if self.refuse:
            raise BusyBarAPIError("Forbidden", status_code=self.refuse)
        return types.StatusFirmware(version="1.2.4")

    async def access(self):
        return types.HttpAccessInfo(mode=self.mode, key_valid=False)

    async def aclose(self):
        pass


class FakeSource:
    name = "Feed"

    async def fetch(self, start, end):
        return []

    async def aclose(self):
        pass


async def check(monkeypatch, capsys, bar, data=None):
    config = Config.model_validate(data or SOURCES)
    monkeypatch.setattr(connect, "make_bar", lambda _config: bar)
    monkeypatch.setattr(connect, "make_sources", lambda _config: [FakeSource()])
    code = await diagnose.check(config)
    return code, capsys.readouterr().out


async def test_check_all_good(monkeypatch, capsys):
    code, out = await check(monkeypatch, capsys, FakeBar())
    assert code == 0
    assert "firmware 1.2.4, API 27.5.0, token accepted" in out
    assert "Feed: no events in the next 7 days" in out
    assert "All good." in out


async def test_check_explains_a_refused_lan_call(monkeypatch, capsys):
    lan = {**SOURCES, "bar": {"address": "192.168.1.50", "token": "x" * 43}}
    code, out = await check(monkeypatch, capsys, FakeBar(refuse=403), lan)
    assert code == 1
    assert "HTTP API over Wi-Fi is disabled" in out

    code, out = await check(monkeypatch, capsys, FakeBar(refuse=403, mode="key"), lan)
    assert "43 characters" in out and "cloud token" in out


def test_a_missing_config_says_how_to_make_one(tmp_path):
    from busybar_calendar.config import load

    with pytest.raises(ConfigError, match="busybar-calendar init"):
        load(tmp_path / "nope.toml")


async def test_status_without_a_config(monkeypatch, capsys):
    from busybar_calendar import service

    monkeypatch.setattr(service, "status", lambda: service.Status(False, False))
    monkeypatch.setattr(service, "recent_log", lambda state: [])
    assert await diagnose.status(None) == 0
    out = capsys.readouterr().out
    assert "not installed" in out and "busybar-calendar install" in out
    assert "busybar-calendar init" in out


async def test_status_shows_now_and_next(monkeypatch, capsys, tmp_path):
    from datetime import UTC, datetime, timedelta

    from busybar_calendar import service
    from busybar_calendar.events import CalendarRef, Event

    log = tmp_path / "busybar-calendar.log"
    log.write_text("16:40:19 reminder: Design review\n")
    monkeypatch.setattr(service, "status", lambda: service.Status(True, True, pid=4321, log=log))
    now = datetime.now(UTC)
    ref = CalendarRef("Feed", "Feed", 0)
    running = Event(
        "a", "Design review", now - timedelta(minutes=5), now + timedelta(minutes=25), ref
    )
    later = Event("b", "Retro", now + timedelta(hours=2), now + timedelta(hours=3), ref)

    class Source:
        name = "Feed"

        async def fetch(self, start, end):
            return [running, later]

        async def aclose(self):
            pass

    monkeypatch.setattr(connect, "make_sources", lambda config: [Source()])
    assert await diagnose.status(Config.model_validate(SOURCES)) == 0
    out = capsys.readouterr().out
    assert "running, pid 4321" in out
    assert "reminder: Design review" in out  # the log tail
    assert "now status: Design review" in out
    assert "next reminder: Retro" in out


def test_version(capsys):
    from busybar_calendar import __version__

    with pytest.raises(SystemExit) as done:
        cli.main(["--version"])
    assert done.value.code == 0
    assert capsys.readouterr().out.strip() == f"busybar-calendar {__version__}"
    assert __version__[0].isdigit()  # read from the installed package


async def test_check_as_json(monkeypatch, capsys):
    import argparse
    import json

    config = Config.model_validate(SOURCES)
    monkeypatch.setattr(connect, "make_bar", lambda _config: FakeBar())
    monkeypatch.setattr(connect, "make_sources", lambda _config: [FakeSource()])
    code = await cli.cmd_check(config, argparse.Namespace(json=True))  # through the CLI
    result = json.loads(capsys.readouterr().out)  # nothing else on stdout
    assert code == 0
    assert result["ok"] is True
    bar, calendar = result["findings"]
    assert (bar["area"], bar["firmware"], bar["api"]) == ("bar", "1.2.4", "27.5.0")
    assert (calendar["area"], calendar["source"], calendar["events"]) == ("calendar", "Feed", 0)


async def test_status_as_json(monkeypatch, capsys):
    import argparse
    import json
    from datetime import UTC, datetime, timedelta

    from busybar_calendar import service
    from busybar_calendar.events import CalendarRef, Event

    monkeypatch.setattr(
        service, "status", lambda: service.Status(True, False, detail="last exit code 1")
    )
    monkeypatch.setattr(service, "recent_log", lambda state: ["Feed: 401, check the credentials"])
    now = datetime.now(UTC)
    later = Event(
        "b",
        "Retro",
        now + timedelta(hours=2),
        now + timedelta(hours=3),
        CalendarRef("Feed", "Feed", 0),
        "tentative",
    )

    class Source:
        name = "Feed"

        async def fetch(self, start, end):
            return [later]

        async def aclose(self):
            pass

    monkeypatch.setattr(connect, "make_sources", lambda config: [Source()])
    await cli.cmd_status(Config.model_validate(SOURCES), argparse.Namespace(json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["service"] == {
        "installed": True,
        "running": False,
        "pid": None,
        "detail": "last exit code 1",
        "log": None,
        "recent_log": ["Feed: 401, check the credentials"],
    }
    assert data["calendar"]["now"] is None
    nxt = data["calendar"]["next"]
    assert (nxt["kind"], nxt["title"], nxt["response"]) == ("reminder", "Retro", "tentative")
    assert datetime.fromisoformat(nxt["at"]) < datetime.fromisoformat(nxt["start"])


async def test_check_tells_a_refused_token_from_an_unreachable_bar(monkeypatch, capsys):
    class RefusingCloud(FakeBar):
        async def version(self):  # the cloud wants a valid token for every call
            raise BusyBarAPIError("Forbidden", status_code=403)

    code, out = await check(monkeypatch, capsys, RefusingCloud())
    assert code == 1
    assert "refused (403)" in out and "cloud token is wrong" in out
    assert "unreachable" not in out

    class Offline(FakeBar):
        async def version(self):
            raise ConnectionError("no route to host")

    code, out = await check(monkeypatch, capsys, Offline())
    assert "unreachable (no route to host)" in out


async def test_check_names_the_calendars_a_typo_could_have_meant(monkeypatch, capsys):
    from zoneinfo import ZoneInfo

    from busybar_calendar import sources
    from busybar_calendar.caldav import RemoteCalendar

    data = {
        "sources": [{"name": "Work", "type": "caldav", "url": "https://x", "include": ["Wrok"]}]
    }
    config = Config.model_validate(data)
    item = sources.CalDAVSource(config.sources[0], 0, ZoneInfo("UTC"), True)
    found = [RemoteCalendar("https://x/1/", "Team"), RemoteCalendar("https://x/2/", "Work")]

    async def calendars():
        return found

    async def fetch(start, end):
        raise AssertionError("no calendar is used, so nothing should be fetched")

    item.calendars, item.fetch = calendars, fetch
    monkeypatch.setattr(connect, "make_bar", lambda _config: FakeBar())
    monkeypatch.setattr(connect, "make_sources", lambda _config: [item])
    assert await diagnose.check(config) == 1
    out = capsys.readouterr().out
    assert "no calendar matches 'Wrok'; there are: Team, Work" in out
    assert "no events" not in out  # no false all-clear for a source that reads nothing
    await item.aclose()


def test_restart(monkeypatch, capsys):
    from busybar_calendar import service

    monkeypatch.setattr(service, "restart", lambda: True)
    assert cli.main(["restart"]) == 0
    assert "Restarted" in capsys.readouterr().out
    monkeypatch.setattr(service, "restart", lambda: False)
    assert cli.main(["restart"]) == 1
    assert "Not installed" in capsys.readouterr().out


def test_bare_command_suggests_first_steps(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "none"))
    monkeypatch.delenv("BUSYBAR_CALENDAR_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "No config yet" in out and "busybar-calendar init" in out


def test_bare_command_shows_status_once_configured(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.toml"
    config.write_text('[[sources]]\nname = "Feed"\ntype = "ics"\nurl = "https://x"\n')
    seen = []

    async def fake_status(loaded, as_json=False):
        seen.append(loaded.sources[0].name)
        return 0

    monkeypatch.setattr(diagnose, "status", fake_status)
    assert cli.main(["-c", str(config)]) == 0
    assert seen == ["Feed"]
    assert "--help lists every command" in capsys.readouterr().out


def test_a_failing_launchctl_is_one_line_not_a_traceback(tmp_path, monkeypatch, capsys):
    import subprocess

    from busybar_calendar import service

    config = tmp_path / "config.toml"
    config.write_text('[[sources]]\nname = "Feed"\ntype = "ics"\nurl = "https://x"\n')
    monkeypatch.setattr(service, "_home", lambda: tmp_path)

    def refuse(plan):
        raise subprocess.CalledProcessError(5, ["launchctl", "bootstrap", "gui/501", "x.plist"])

    monkeypatch.setattr(service, "install", refuse)
    assert cli.main(["-c", str(config), "install", "--force"]) == 1
    err = capsys.readouterr().err
    assert "launchctl bootstrap gui/501 x.plist failed (exit 5)" in err
