import stat

from busybar_calendar import wizard
from busybar_calendar.caldav import CalDAVAuthError, RemoteCalendar
from busybar_calendar.config import load

FOUND = [
    RemoteCalendar("https://dav.example.com/cal/me/1001/", "Home"),
    RemoteCalendar("https://dav.example.com/cal/me/1002/", "Work"),
    RemoteCalendar("https://dav.example.com/cal/me/2001/", "Room 1 (6 people)"),
]


def script(*answers):
    pending = list(answers)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return pending.pop(0)

    ask.asked = asked
    return ask


class FakeStore:
    def __init__(self, keychain=True):
        self.saved = []
        self.keychain = keychain

    def save(self, service, account, env):
        self.saved.append((service, account))
        if self.keychain:
            return wizard.Secret(command=["security", "find-generic-password", "-s", service, "-w"])
        return wizard.Secret(env=env)


def test_cloud_and_an_icloud_account(tmp_path):
    path = tmp_path / "busybar-calendar" / "config.toml"
    # cloud (default), CalDAV (default), username, the suggested server, two calendars
    ask = script("", "", "me@icloud.com", "", "2, 1")
    store = FakeStore()
    assert wizard.run(path, ask=ask, store=store, discover=lambda source: FOUND) == 0

    assert "[https://caldav.icloud.com]" in ask.asked[3]  # suggested from the address
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    config = load(path)
    assert config.bar.address is None
    assert config.bar.token.command[-2:] == ["busybar-calendar-bar", "-w"]
    [source] = config.sources
    assert (source.name, source.url, source.username) == (
        "iCloud",
        "https://caldav.icloud.com",
        "me@icloud.com",
    )
    assert source.include == ["Home", "Work"]  # in the server's order
    assert store.saved == [
        ("busybar-calendar-bar", "busybar-calendar"),
        ("busybar-calendar-icloud.com", "me@icloud.com"),
    ]


def test_usb_and_an_ics_link(tmp_path):
    path = tmp_path / "config.toml"
    ask = script("3", "2", "webcal://example.com/team.ics")
    assert wizard.run(path, ask=ask, store=FakeStore(), discover=None) == 0
    config = load(path)
    assert config.bar.address == "10.0.4.20"
    assert config.bar.token.resolve() is None
    assert (config.sources[0].type, config.sources[0].url) == (
        "ics",
        "https://example.com/team.ics",
    )


def test_wifi_without_a_keychain_and_a_failed_sign_in(tmp_path, capsys):
    path = tmp_path / "config.toml"

    def refuse(source):
        raise CalDAVAuthError("PROPFIND https://dav.example.com: 401, check the credentials", 401)

    ask = script("2", "192.168.1.50", "1", "me@example.com", "https://dav.example.com")
    assert wizard.run(path, ask=ask, store=FakeStore(keychain=False), discover=refuse) == 0
    out = capsys.readouterr().out
    assert "Could not sign in" in out
    text = path.read_text()
    assert 'token_env = "BUSYBAR_TOKEN"' in text
    assert 'password_env = "CALDAV_PASSWORD"' in text
    assert "include" not in text
    assert load(path).sources[0].name == "example.com"


def test_all_calendars_when_none_are_picked(tmp_path):
    path = tmp_path / "config.toml"
    ask = script("3", "1", "me@example.com", "https://dav.example.com", "")
    wizard.run(path, ask=ask, store=FakeStore(), discover=lambda source: FOUND)
    assert load(path).sources[0].include == []


def test_bad_answers_are_asked_again(tmp_path):
    path = tmp_path / "config.toml"
    ask = script("9", "x", "3", "2", "https://example.com/a.ics")
    assert wizard.run(path, ask=ask, store=FakeStore(), discover=None) == 0
    assert len(ask.asked) == 5


def test_an_existing_config_is_kept_unless_confirmed(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("keep me")
    assert wizard.run(path, ask=script("n"), store=FakeStore(), discover=None) == 1
    assert path.read_text() == "keep me"
    ask = script("y", "3", "2", "https://example.com/a.ics")
    assert wizard.run(path, ask=ask, store=FakeStore(), discover=None) == 0
    assert "keep me" not in path.read_text()
