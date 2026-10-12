# busybar-calendar

Calendar reminders for the [BUSY Bar](https://busy.app) from any CalDAV
account or published ICS feed: iCloud, Fastmail, Nextcloud, Zoho, Yahoo,
mailbox.org, self-hosted servers, or an Outlook/Proton calendar shared by
link.

The bar shows them the way it shows events from its built-in
[Google Calendar integration](https://docs.busy.app/bar/apps-and-integrations/google-calendar):
a reminder with a countdown before the event, then a status while it runs,
with the same per-calendar settings. Only the source differs. BUSY Cloud
talks to Google; this talks to a URL you give it, and draws through the
bar's own [HTTP API](https://docs.busy.app/bar/dev/http-api), on the LAN or
through BUSY Cloud.

Requested upstream in
[busy-app/busybar-firmware#1086](https://github.com/busy-app/busybar-firmware/issues/1086);
this runs today, on a machine of your own.

## What the bar shows

| When | Front display | Sound |
| --- | --- | --- |
| `minutes_before` the start | calendar-reminder animation, title, countdown to the start | `calendar_reminder_ends` |
| During the event | calendar-event animation, title, countdown to the end, or a status animation such as `meeting` | `calendar_event_starts` |
| After it ends | whatever was there before | |

These are the bar's own stock animations and sounds. Drawings go in at
priority 91, above an active BUSY session (90), so like Google events they
show on top of any status. Each element carries `display_until`, so the bar
removes it on time even if this service has stopped.

Rules, following the Google integration:

- Events of 24 hours or more, and all-day events, are not shown.
- When events overlap, the newest event wins, and between events starting
  together, the calendar listed last. A reminder for your next meeting
  therefore replaces the status of the one still running.
- Also skipped: cancelled events, events marked free (`skip_free`), and
  invitations you declined (matched on `emails`, which defaults to the
  CalDAV username when it is an email address).

## Settings

The per-calendar settings are Google's:

| Google Calendar integration | here |
| --- | --- |
| Event reminders: on/off | `reminder.enabled` |
| How long before the event | `reminder.minutes_before` |
| Sound | `reminder.sound` |
| Show event name | `reminder.show_name` |
| Status during events: on/off | `status.enabled` |
| Event name, or a status from the list | `status.show`: `name`, `meeting`, `on_call`, ... |
| Sound | `status.sound` |

They layer: `[defaults]` for every calendar, overridden per source, then per
calendar (`[sources.calendars."Work".reminder]`). Setting a default once is
the account-level setting BUSY Cloud lacks
([busybar-firmware#1083](https://github.com/busy-app/busybar-firmware/issues/1083)).
See [`config.example.toml`](config.example.toml) for all of it.

## Setup

1. Turn on the bar's HTTP API over Wi-Fi: connect it by USB, open
   `http://10.0.4.20`, then **Network -> HTTP API -> Set password and enable**.
   Or skip this and use a BUSY Cloud token with the **BUSY Bar** access
   scope instead of an address.
2. Install and configure:

   ```sh
   uv tool install git+https://github.com/kurok/busybar-calendar
   cp config.example.toml config.toml   # then edit it
   export BUSYBAR_TOKEN=...              # the bar's HTTP API password
   ```

3. Check it:

   ```sh
   busybar-calendar calendars   # what each CalDAV account has
   busybar-calendar upcoming    # what the bar will show, and when
   busybar-calendar demo        # draw a sample reminder for 20 seconds
   busybar-calendar demo --status --show meeting
   ```

4. Run it: `busybar-calendar run`.

Passwords can come from the environment (`password_env`) or a command
(`password_command`, run without a shell), for example the macOS keychain:

```sh
security add-generic-password -s busybar-icloud -a me@icloud.com -w
```

### Keep it running

macOS, as a launchd agent (`~/Library/LaunchAgents/app.busybar.calendar.plist`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>app.busybar.calendar</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/me/.local/bin/busybar-calendar</string>
    <string>--config</string><string>/Users/me/.config/busybar-calendar/config.toml</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

Docker, on a home server or a Raspberry Pi:

```sh
docker build -t busybar-calendar .
docker run -d --restart unless-stopped -e BUSYBAR_TOKEN \
  -v "$PWD/config.toml:/config/config.toml:ro" busybar-calendar
```

## How it works

CalDAV discovery follows RFC 6764 and RFC 4791: `/.well-known/caldav`, then
`current-user-principal`, then `calendar-home-set`, then the calendars that
hold events. A calendar collection URL also works directly. Events come from
a `calendar-query` REPORT over the next `lookahead_hours`. Recurrence (RRULE,
EXDATE, moved occurrences) is expanded here with
[recurring-ical-events](https://github.com/niccokunzmann/python-recurring-ical-events),
not by the server, because servers differ in how well they do it. ICS feeds
are fetched with `If-None-Match`.

A source that fails keeps its last good events, so a server hiccup does not
take a running meeting off the bar. The loop sleeps until the next moment
the screen can change, so reminders appear on time rather than on the next
poll.

Titles are folded to ASCII for the bar's bitmap fonts
(`Планування` -> `Planuvannya`), and emoji are dropped.
`title_font = "global"` keeps them in their own script.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## License

MIT
