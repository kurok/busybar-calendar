from pathlib import Path

import pytest
from busylib import types
from busylib.exceptions import BusyBarAPIError

from busybar_calendar import cli
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
    monkeypatch.setattr(cli, "_bar", lambda _config: bar)
    monkeypatch.setattr(cli, "_sources", lambda _config: [FakeSource()])
    code = await cli.cmd_check(config, None)
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
    assert await cli.cmd_status(None, None) == 0
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

    monkeypatch.setattr(cli, "_sources", lambda config: [Source()])
    assert await cli.cmd_status(Config.model_validate(SOURCES), None) == 0
    out = capsys.readouterr().out
    assert "running, pid 4321" in out
    assert "reminder: Design review" in out  # the log tail
    assert "now status: Design review" in out
    assert "next reminder: Retro" in out
