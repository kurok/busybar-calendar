import plistlib
from pathlib import Path

import pytest

from busybar_calendar import service


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def ran(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs.get("check", False)))

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    return calls


def test_launchd_agent(home):
    plan = service.install_plan(Path("cfg/config.toml"), "darwin")
    assert plan.path == home / "Library/LaunchAgents/app.busybar.calendar.plist"
    agent = plistlib.loads(plan.content)
    assert agent["ProgramArguments"][1:] == ["-m", "busybar_calendar", "run"]
    # An absolute config path, so the agent does not depend on a working directory.
    assert Path(agent["EnvironmentVariables"]["BUSYBAR_CALENDAR_CONFIG"]).is_absolute()
    assert agent["RunAtLoad"] and agent["KeepAlive"]
    assert agent["ThrottleInterval"] == service.RESTART_AFTER
    assert plan.commands[0][:2] == ["launchctl", "bootstrap"]


def test_systemd_unit(home):
    config = (home / "cal.toml").resolve()
    plan = service.install_plan(config, "linux")
    assert plan.path == home / ".config/systemd/user/busybar-calendar.service"
    unit = plan.content.decode()
    assert f"Environment=BUSYBAR_CALENDAR_CONFIG={config}" in unit
    assert "-m busybar_calendar run" in unit
    assert f"RestartSec={service.RESTART_AFTER}" in unit
    assert plan.commands[-1] == ["systemctl", "--user", "enable", "--now", service.UNIT]


def test_other_platforms_are_refused():
    with pytest.raises(OSError, match="macOS and Linux"):
        service.install_plan(Path("c.toml"), "win32")


def test_install_writes_then_loads(home, ran):
    plan = service.install_plan(Path("c.toml"), "darwin")
    service.install(plan)
    assert plan.path.read_bytes() == plan.content
    assert plan.log.parent.is_dir()
    # Unloading an older agent may fail; loading the new one must not.
    assert ran == [(list(plan.cleanup[0]), False), (plan.commands[0], True)]


def test_uninstall(home, ran):
    plan = service.uninstall_plan("linux")
    assert service.uninstall(plan) is False  # nothing installed
    plan.path.parent.mkdir(parents=True)
    plan.path.write_text("[Unit]\n")
    assert service.uninstall(plan) is True
    assert not plan.path.exists()
    assert [c for c, _ in ran] == [list(plan.cleanup[0]), plan.commands[0]]


def test_systemd_quotes_paths_with_spaces():
    unit = service.systemd_unit(["/opt/my tools/python", "-m", "x"], Path("/a b/c.toml"))
    text = unit.decode()
    assert 'Environment="BUSYBAR_CALENDAR_CONFIG=/a b/c.toml"' in text
    assert 'ExecStart="/opt/my tools/python" -m x' in text
