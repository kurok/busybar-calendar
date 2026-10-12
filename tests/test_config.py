import pytest
from pydantic import ValidationError

from busybar_calendar.config import Config, ConfigError, load


def base(**source):
    return {"sources": [{"name": "Work", "type": "caldav", "url": "https://dav.example", **source}]}


def test_settings_layer_defaults_source_calendar():
    config = Config.model_validate(
        {
            "defaults": {"reminder": {"minutes_before": 3, "sound": False}},
            "sources": [
                {
                    "name": "Work",
                    "type": "caldav",
                    "url": "https://dav.example",
                    "reminder": {"minutes_before": 10},
                    "calendars": {
                        "Team": {"status": {"show": "meeting"}, "reminder": {"sound": True}}
                    },
                }
            ],
        }
    )
    reminder, status = config.settings_for("Work", "Personal")
    assert (reminder.minutes_before, reminder.sound, status.show) == (10, False, "name")
    reminder, status = config.settings_for("Work", "Team")
    assert (reminder.minutes_before, reminder.sound, status.show) == (10, True, "meeting")


def test_rejects_unknown_status_and_typos():
    with pytest.raises(ValidationError, match="show must be"):
        Config.model_validate(base(status={"show": "partying"})).settings_for("Work", "x")
    with pytest.raises(ValidationError):
        Config.model_validate(base(urll="x"))


def test_load_validates_every_calendar(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text(
        '[[sources]]\nname = "W"\ntype = "caldav"\nurl = "https://x"\n'
        "[sources.calendars.Team.reminder]\nminutes_before = 0\n"
    )
    with pytest.raises(ValidationError, match="minutes_before"):
        load(path)


def test_webcal_and_emails():
    config = Config.model_validate(
        {
            "sources": [
                {"name": "Feed", "type": "ics", "url": "webcal://cal.example/a.ics"},
                {
                    "name": "Mail",
                    "type": "caldav",
                    "url": "https://x",
                    "username": "me@example.com",
                },
            ]
        }
    )
    assert config.sources[0].url == "https://cal.example/a.ics"
    assert config.sources[1].emails == ["me@example.com"]


def test_ics_has_no_calendars():
    with pytest.raises(ValidationError, match="caldav only"):
        Config.model_validate(
            {"sources": [{"name": "Feed", "type": "ics", "url": "https://x", "include": ["a"]}]}
        )


def test_unique_source_names():
    with pytest.raises(ValidationError, match="unique"):
        Config.model_validate(
            {
                "sources": [
                    {"name": "A", "type": "ics", "url": "https://x"},
                    {"name": "A", "type": "ics", "url": "https://y"},
                ]
            }
        )


def test_secrets(monkeypatch):
    monkeypatch.setenv("APP_PW", "from-env")
    config = Config.model_validate(base(username="u", password_env="APP_PW"))
    assert config.sources[0].password.resolve() == "from-env"
    config = Config.model_validate(base(password_command=["echo", "from-cmd"]))
    assert config.sources[0].password.resolve() == "from-cmd"
    config = Config.model_validate({**base(), "bar": {"token": "inline"}})
    assert config.bar.token.resolve() == "inline"
    assert Config.model_validate(base()).bar.token.resolve() is None

    monkeypatch.delenv("APP_PW")
    config = Config.model_validate(base(password_env="APP_PW"))
    with pytest.raises(ConfigError, match="APP_PW"):
        config.sources[0].password.resolve()
    with pytest.raises(ValidationError, match="only one of"):
        Config.model_validate(base(password="a", password_env="APP_PW"))
