# busybar-calendar

Calendar reminders for the [BUSY Bar](https://busy.app) from **any CalDAV
account or ICS feed**, shown exactly the way the bar shows its built-in
Google Calendar events.

![A reminder on the BUSY Bar: calendar icon, title and countdown](docs/images/reminder.gif)

The bar's own [Google Calendar integration](https://docs.busy.app/bar/apps-and-integrations/google-calendar)
runs in BUSY Cloud and only talks to Google. This does the same thing for
iCloud, Fastmail, Nextcloud, PrivateEmail, self-hosted CalDAV servers, and
any calendar published as an ICS link (Outlook, Google, Proton). It runs on
a machine of yours and draws through the bar's
[HTTP API](https://docs.busy.app/bar/dev/http-api), via BUSY Cloud or on the
LAN. The events look the same as Google's; only where they come from is
different. Requested upstream as
[busybar-firmware#1086](https://github.com/busy-app/busybar-firmware/issues/1086).

## On the bar

Every picture here is a frame read back from a real bar (firmware 1.2.4)
through `GET /api/screen`.

| | |
| --- | --- |
| **Before the event** - a red calendar, the title, and a countdown to the start. | ![Reminder](docs/images/reminder.gif) |
| **During the event** - a red calendar, the title, a countdown to the end and a red **BUSY** ... | ![Status with the event name](docs/images/status.png) |
| **Marked "Maybe"** (tentative): a yellow calendar and a yellow **BUSY**, in the reminder and during the event, so you can tell it from one you accepted. | ![Status of a tentative event](docs/images/status-tentative.png) |
| ... or one of the bar's own statuses, such as `meeting`, `on_call` or `dnd`. | ![Meeting status](docs/images/status-meeting.gif) |
| **Long titles** scroll beside the icon. | ![Scrolling title](docs/images/long-title.gif) |
| **Titles in other scripts** are transliterated for the bar's bitmap fonts (`Планування спринту` becomes `Planuvannya sprintu`) ... | ![Transliterated title](docs/images/cyrillic-transliterated.gif) |
| ... or drawn as they are with `title_font = "global"`, on one line beside the countdown. | ![Cyrillic title in the global font](docs/images/cyrillic-global.gif) |
| **Event name hidden** for a calendar (`show_name = false`). | ![Hidden name](docs/images/hidden-name.png) |

Like Google events, these go in above an active BUSY session, so they show
on top of any status. A sound plays as a reminder opens and as an event
starts, using the bar's own calendar sounds. After the event, the bar goes
back to whatever it was showing.

## Screen designs

Four designs for the same information. `busybar-calendar init` asks which one to
draw, and the first, the default, is what you get if you do not choose. To change
it later, set `layout` under `[display]`; the running service applies it within a
minute.

| Design | An event you accepted | Marked "Maybe" |
| --- | --- | --- |
| **1. Default** (`default`): the calendar icon, the title, a ticking countdown and BUSY. A Maybe gets a yellow calendar and a yellow BUSY. | ![Default design](docs/images/status.png) | ![Default design, Maybe](docs/images/status-tentative.png) |
| **2. Banner** (`banner`): the title on a band of the state colour, the countdown and BUSY below. Red when accepted, white before the start, and a yellow outline for a Maybe. | ![Banner design](docs/images/design-banner.png) | ![Banner design, Maybe](docs/images/design-banner-maybe.png) |
| **3. Bold title** (`bold_title`): the title in the larger 7 px font, the countdown and the label in the state colour, no icon. A Maybe says MAYBE. | ![Bold title design](docs/images/design-bold-title.png) | ![Bold title design, Maybe](docs/images/design-bold-title-maybe.png) |
| **4. Words** (`words`): the default look, with the response in words: MAYBE where BUSY would be, already in the reminder. | ![Words design](docs/images/design-words.png) | ![Words design, Maybe](docs/images/design-words-maybe.png) |

The countdown ticks on the bar itself in all four. Banner and Bold title draw the
title in the 7 px font (the 11 px `global` font with `title_font = "global"`), so
`title_font = "small"` and the icon options do not apply to them. A title that does
not fit scrolls, in every design. A Maybe looks like an accepted event when
`tentative_yellow` is off.

The three extra designs were picked from ten whole-screen concepts, each scored on
legibility, how well it tells a Maybe from an accepted event (also for red-green
colour blindness), information, stress cases, load on the panel, and effort to run;
those scoring over 70 of 100 were kept. Banner's filled red band has black lettering
that reads best close up; the hollow Maybe band reads best from a distance.

## Features

- **CalDAV** with discovery (`/.well-known/caldav`, principal, calendar home),
  or a calendar URL directly; Basic or Digest auth.
- **Calendar filters**: `include` / `exclude` by name, id or URL, with
  wildcards (`exclude = ["Room *"]`).
- **ICS / webcal** feeds, fetched with `If-None-Match`.
- **Recurring events** expanded locally (RRULE, EXDATE, moved occurrences),
  timezones and floating times handled.
- **Google's per-calendar settings** (reminder time, sound, show name,
  status), set once as defaults and overridden per source or per calendar.
- **Rules by title**, from any calendar: keep `Focus time` off the bar,
  show `Lunch*` as the bar's own lunch status.
- **Overlaps settled by your response**: an event you accepted wins over
  one you marked tentative, which wins over one you have not answered - when
  they start together and when they are shifted against each other, so a
  "maybe" never covers a meeting you said yes to; then, as in Google's
  integration, the newest event wins.
- **"Maybe" in yellow**: an event you marked tentative gets a yellow
  calendar and a yellow BUSY, so you can tell it from one you accepted
  (`display.tentative_yellow`, default on).
- **Google's filters**: no all-day or 24-hour-plus events. Also skipped:
  cancelled events, events marked free, invitations you declined.
- **On time**: the loop wakes at the next change, not on the next poll.
- **Live config**: the running service applies an edited config within a
  minute; an edit that does not load is left out, and the log says why.
- **Resilient**: a failing source keeps its last good events; a bar that
  cannot be reached is retried; drawings expire on the bar by themselves
  if the service stops.
- **No secrets in files**: passwords and tokens come from the environment
  or a command such as the macOS Keychain.

## Get started

```sh
uv tool install git+https://github.com/kurok/busybar-calendar
busybar-calendar init     # a few questions: how to reach the bar, which calendar
busybar-calendar check    # proves it works, or says what to fix
busybar-calendar install  # runs it in the background from now on
```

`init` asks how to reach the bar (BUSY Cloud, Wi-Fi or USB) and which
calendar to read, keeps the passwords in the macOS Keychain (libsecret on
Linux), signs in so you can pick calendars, and writes
`~/.config/busybar-calendar/config.toml`. To write the config yourself,
start from [`config.example.toml`](config.example.toml).

## Everyday commands

| Command | |
| --- | --- |
| `busybar-calendar` | Where you stand: the first steps before setup, the status after. |
| `busybar-calendar status` | Is it running, what did it last log, what is on the bar now and next. |
| `busybar-calendar check` | The bar, its token and every calendar, with what to fix. |
| `busybar-calendar add` | Another calendar, by the same questions as `init`. |
| `busybar-calendar restart` | After a new password or a `[bar]` change; other config edits apply by themselves within a minute. |
| `busybar-calendar upcoming` | The events the bar will show, and when; tentative ones marked. |
| `busybar-calendar calendars` | What each CalDAV account has, with ids, for `include`. |
| `busybar-calendar replay` | Tomorrow's events on the bar, a minute each. |
| `busybar-calendar demo` | A sample reminder on the bar, to see the look. |
| `busybar-calendar uninstall` | Stop and remove the background service. |

`status` and `check` also take `--json`, for scripts. A newer version is
`uv tool upgrade busybar-calendar && busybar-calendar restart` - or, with
`busybar-calendar install --auto-update`, the service fetches it by itself
every time it starts or restarts.

## As a BUSY Bar gallery app

`app.py` follows the [community gallery](https://github.com/maxswinkels/busybar-apps)'s
conventions: one entrypoint, `--host` (default `10.0.4.20`, the bar over
USB), secrets from the environment only. It runs from a clone:

```sh
git clone https://github.com/kurok/busybar-calendar.git && cd busybar-calendar
pip install -r requirements.txt
python app.py                        # the config init wrote; a demo schedule before that
python app.py --host 192.168.1.50 --ics "https://example.com/work.ics"
CALDAV_PASSWORD=... python app.py --caldav https://caldav.icloud.com --user me@icloud.com
BUSYBAR_TOKEN=... python app.py --cloud --ics "https://example.com/work.ics"
```

`CALDAV_PASSWORD` is the calendar's password, `BUSYBAR_TOKEN` the bar's HTTP
API password or, with `--cloud`, a BUSY Cloud token. On macOS the first
start after installing the requirements takes a few seconds while the system
checks the new libraries; later starts take a fraction of a second.

## Settings

The per-calendar settings are the Google Calendar integration's:

| Google Calendar integration | `config.toml` |
| --- | --- |
| Event reminders: on/off | `reminder.enabled` |
| How long before the event | `reminder.minutes_before` |
| Sound | `reminder.sound` |
| Show event name | `reminder.show_name` |
| Status during events: on/off | `status.enabled` |
| Event name, or a status from the list | `status.show`: `name`, `meeting`, `on_call`, `dnd`, ... |
| Sound | `status.sound` |
| *(not in Google's)* Busy status for events you marked tentative | `status.tentative` (default on) |
| *(not in Google's)* Yellow calendar and BUSY for events you marked tentative | `display.tentative_yellow` (default on) |
| *(not in Google's)* Which screen design | `display.layout`: `default`, `banner`, `bold_title`, `words` |

They layer: `[defaults]` for every calendar, then per source, then per
calendar (`[sources.calendars."Work".reminder]`); a default set once is the
account-level setting BUSY Cloud does not have yet
([busybar-firmware#1083](https://github.com/busy-app/busybar-firmware/issues/1083)).
Last come the `[[titles]]` rules, which match event titles in any calendar:

```toml
[[titles]]
match = ["Focus time", "Commute*"]   # * and ? are wildcards; case does not matter
reminder.enabled = false
status.enabled = false
```

`[display]` sets the look: the screen design (`layout`, see above), the icons
(`red_calendar` or the bar's own `animation`), the word beside the countdown
(`busy_label`, `busy_color`) and whether events you marked tentative are drawn in
yellow (`tentative_yellow`).
Every option, with its default, is in the
[configuration reference](docs/configuration.md).

## Documentation

- [Setup](docs/setup.md) - the bar, calendar providers, secrets, running as a service.
- [Troubleshooting](docs/troubleshooting.md) - what `check` and `status` say when something is wrong, and the fix.
- [Configuration reference](docs/configuration.md) - every option and its default, generated from the code.
- [Changelog](CHANGELOG.md) - what changed in each version.
- [How it works](docs/how-it-works.md) - the design, the API calls, and what was measured on the hardware.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

`scripts/capture_screens.py` regenerates `docs/images` from a real bar.

## License

MIT, except the red and yellow calendar icons in `src/busybar_calendar/icons.py`:
they are redrawn from Google's [Noto Emoji](https://github.com/googlefonts/noto-emoji)
📅 and stay under the SIL Open Font License 1.1
([LICENSES/noto-emoji-OFL.txt](LICENSES/noto-emoji-OFL.txt)).
