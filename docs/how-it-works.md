# How it works

## Why a service, and not an app on the bar

The bar's Google Calendar integration lives in BUSY Cloud, which is not
open source. Reading the firmware shows how it reaches the bar: the cloud
sends ordinary HTTP API requests through an MQTT proxy on the device
(`mqtt_http_proxy.c`). There is no calendar endpoint, on the bar or in the
cloud's device API. A Google event on the bar is made of the same requests
anyone can send:

- `POST /api/display/draw` with the stock calendar animations, a text and a
  countdown element;
- `POST /api/audio/play` with the stock calendar sounds;
- `DELETE /api/display/draw` when it is over.

So anything that makes those requests gets the same events on screen. This
service does that, with a CalDAV account or an ICS feed in place of Google.

A JavaScript app on the bar cannot do the same thing. The firmware runs one
JS app at a time and stops it when you leave it, so it could not put a
reminder on top of a BUSY session or the clock the way the integration does.

```
 CalDAV server ─┐
 ICS feed ──────┤   busybar-calendar                         BUSY Bar
                ├─► sources ─► schedule ─► render ─► runner ─► HTTP API
 (poll)         │   (events)   (what now)  (elements) (draw,    via BUSY Cloud
                                                        clear,  (Bearer token)
                                                        sound)  or the LAN
                                                                (X-API-Token)
```

## The pieces

| Module | Does |
| --- | --- |
| `caldav.py` | Discovery (`/.well-known/caldav`, `current-user-principal`, `calendar-home-set`) and `calendar-query` REPORTs with a time range. Hrefs are joined against the URL that answered, which is what makes iCloud's per-account hosts work. |
| `sources.py` | One class per source type. CalDAV calendars are listed again every 12 refreshes; ICS feeds use `If-None-Match`. |
| `events.py` | iCalendar to events: recurrence expanded with `recurring-ical-events`, times made timezone-aware, and the filters applied. |
| `schedule.py` | Pure logic: which screen is due now, and when that next changes. |
| `render.py` | The display elements for a screen, and its sound. |
| `runner.py` | The loop: refresh, decide, draw or clear, sleep until the next change. |
| `icons.py` | The red and yellow calendars, as XPM2 images drawn inline. |
| `fontmetrics.py` | How wide the 7px and 11px fonts draw text, so a title scrolls only when it has to. |
| `config.py` | The TOML config, its models and where it is found; each option's description lives here. |
| `connect.py` | What every command shares: the bar client, the sources, stopping on a signal. |
| `diagnose.py` | `check` and `status`, as text or JSON. |
| `playback.py` | Showing events outside the schedule: `replay`, the demo, the gallery's test frame. |
| `wizard.py` | `init` and `add`: the questions, the secrets, the config they write. |
| `service.py` | `install`, `uninstall`, the service's state and log: launchd or systemd. |
| `reference.py` | Generates the configuration reference from `config.py`. |
| `cli.py` | The command line: the commands, their options, which code each runs. |

## Rules

Each event can open two screens. A **reminder** runs from `minutes_before`
until the start, and a **status** runs from the start to the end.

- When several screens are due at once:
  1. **your response decides first**: an event you accepted beats one you
     marked tentative, which beats one you have not answered. Events of
     your own, with no attendees, count as accepted. Your response is your
     own attendee entry's `PARTSTAT`, found by your address (`emails`, which
     defaults to the CalDAV username), and it counts even on events you
     organise. Published feeds leave the attendees out; there the event's
     own marking counts instead, Outlook's `X-MICROSOFT-CDO-BUSYSTATUS:TENTATIVE`
     or `STATUS:TENTATIVE`;
  2. then the event starting latest, the Google integration's rule ("the
     newest event and the most recently added calendar take priority"), so
     a reminder for your next meeting replaces the status of the one still
     running, as long as you are as sure to attend the next one;
  3. then the calendar configured last.
- The response ranks whole screens, so it holds however two events are
  placed against each other. With Maybe 10:00-11:00 and Sure 10:30-11:30
  the bar shows Maybe, then Sure from its reminder at 10:25 until it
  ends at 11:30 - Maybe's end at 11:00 changes nothing. With Sure
  10:00-11:00 and Maybe 10:30-11:30, Maybe's reminder and start do not
  cut in, and Maybe appears when Sure ends. A tentative event never takes
  the bar from an accepted one that is showing something.
- An event you marked tentative puts the busy status up like any other,
  unless `status.tentative = false`: then it keeps its reminder but never
  shows as busy, and whatever else is on carries on.
- A tentative event is also drawn differently: a yellow calendar and a yellow
  `BUSY`, in its reminder and its status alike, where an accepted or
  unanswered one gets the red ones. `display.tentative_yellow = false`
  draws them all in red. A calendar icon set to the bar's own `animation`
  stays as it is (the stock animation has no yellow version) and only the
  label turns yellow, and a stock status such as `meeting` is never recoloured.
  Changing your answer on your phone redraws the screen at the next refresh.
- Like Google: events of 24 hours or more, and all-day events, are not
  shown.
- Also skipped: `STATUS:CANCELLED`, `TRANSP:TRANSPARENT` (free) unless
  `skip_free = false`, and invitations you declined or delegated.
- A sound plays when a screen opens, but not when the service starts in
  the middle of one: restarting during a meeting does not chime again.

## Drawing

| Element | Reminder | Status (`show = "name"`) | Status (`show = "meeting"` etc.) |
| --- | --- | --- | --- |
| `cal_xpm` | the red calendar (default) | the red calendar (default) | |
| `cal_xpm_maybe` | the yellow calendar, for a tentative event | the yellow calendar, for a tentative event | |
| `cal_icon` | `shared/animations/calendar_reminder_16x16.anim` with `reminder_icon = "animation"` | `shared/animations/calendar_event_16x16.anim` with `event_icon = "animation"` | |
| `cal_title` | title, `small` font, scrolls if long | title | |
| `cal_time` | countdown to the start | countdown to the end | |
| `cal_busy` | | `BUSY` in red (yellow for a tentative event), right-aligned on the countdown's line | |
| `cal_status` | | | `shared/animations/<status>_72x16.anim` |

The calendar travels inside each drawing as an XPM2 `xpmbitmap`
element (the firmware takes up to 32 colours, full colour on the front
display), so nothing is uploaded to the bar. busylib 2.6 has no model for
that element, so drawings are posted with `api_request` rather than
`display_draw`. The icons are redrawn from Noto Emoji's 📅 at 16x16; see
`icons.py` for the pixels and their licence. The yellow one has an element id of its own
(`cal_xpm_maybe`), so a switch between the colours clears and redraws the
icon instead of depending on the bar swapping an existing bitmap's pixels.

### Screen designs

`[display] layout` picks one of four; the table above is the `default`. The others
draw these elements (a status that is one of the bar's own animations is the same
in every design):

| Design | Elements, in drawing order |
| --- | --- |
| `banner` | `cal_band` (filled `rectangle`, 72x11, in `busy_color`; `cal_band_r`, white, in a reminder; `cal_band_m`, a yellow outline, for a tentative event), `cal_title` (7px font, black on the band; `cal_title_m`, yellow, when tentative), `cal_time` (countdown, bottom row), `cal_busy` (`cal_busy_m` when tentative) |
| `bold_title` | `cal_title` (7px font, white), `cal_time_r` (white, reminder), `cal_time_a` (`busy_color`) or `cal_time_m` (yellow, tentative), `cal_busy` (`BUSY`) or `cal_busy_m` (`MAYBE`, tentative) |
| `words` | as the default, and a tentative event shows `cal_busy_m` (`MAYBE`) in its reminder as well as during the event |

Where a change of look would recolour an element in place (a white band turning red,
a countdown changing colour), the new look has an id of its own, so the runner clears
the screen and draws it afresh rather than relying on the bar to update an existing
rectangle or countdown. A reminder turning into its event keeps the ids, and adds
only what is new, in the default, `words` and a tentative `banner`.

The title is scrolled only when it does not fit, decided from the real width of each
character in the font (`fontmetrics.py`): "Design review" is 65 px in the 7px font,
58 px in the 11px `global` font. The countdown label sits on the last five rows
(y=20 for the countdown, y=9 for the label), the title on the first eleven (y=-1).
With `title_font = "global"` the label still fits in `banner` and `bold_title`, but not
in `words`, which keeps the default layout's one line.

Sounds: `shared/sounds/calendar_reminder_ends.snd` when a reminder opens and
`shared/sounds/calendar_event_starts.snd` when an event starts. Both can be
changed under `[display]`.

Drawings go in at priority 91. The firmware uses 10 for its built-in apps
and 90 for an active BUSY session, so like Google events these appear above
a running session. Every element carries `display_until`, so the bar takes
the drawing down by itself if the service stops.

## Measured on the hardware

The layout and timing were checked on a bar running firmware 1.2.4 / API
27.5.0, by drawing each screen and reading the pixels back with
`GET /api/screen` (the source of the pictures in the README). That turned
up things the API description does not say:

- **The countdown sits high in its box.** Countdown elements use the 7px
  `superscript` font, which puts its digits 4px above the bottom of the
  element. Anchored `bottom_left` at y=16, the digits landed on rows 7-11,
  into the title's descenders. At y=19 they land on rows 10-14, level with
  the icon's last row. Beside a `global`-font title, the countdown sits at
  y=9 so both share rows 6-10.
- **A redraw at the moment of expiry loses its animation.** Redrawing an
  element at the same instant its old `display_until` fires drops the
  animated icon (0 of 256 icon pixels lit). With the old expiry even a few
  seconds later, the redraw keeps it. So `display_until` is the screen's
  end plus 60 seconds: the service redraws or clears on time anyway, and
  the extra minute only matters if it has stopped.
- **A draw merges by element id.** It updates the ids it names and leaves
  the others up, so drawing the `meeting` animation after a reminder would
  leave the reminder's elements underneath. The service clears its own
  drawing first only when an element would be left over, and otherwise
  updates in place. A reminder turning into its event only adds BUSY, so
  that change is seamless: sampling the screen across it, clearing first
  caught a half-drawn icon (96 of 234 pixels lit) in 1 of 20 frames, and
  updating in place showed the full icon in all 20.
- **The screen has one owner.** `DELETE /api/display/draw` with this
  application's name, while another application is on screen, answers
  `400 this application_name is currently not displaying anything`. The
  service takes that as "already clear" rather than an error to retry.
- **Text is not ASCII-only.** The published schema limits `text` to
  printable ASCII, but the firmware accepts any text, and the `global` font
  (Lana Pixel 11) draws Cyrillic. The default stays the schema-conforming
  `small` font with transliteration; `title_font = "global"` is opt-in.
- **LAN tokens are 32 characters at most**, and over Wi-Fi nothing but
  `/api/version`, `/api/access` and `/api/transport` answers while the
  HTTP API is disabled.
- Through BUSY Cloud, a reminder, its start and its end each reached the
  bar within half a second of the event's time.

## Limits

- Changes are seen on the next poll (`poll_minutes`, default 5), and ICS
  feeds are only as fresh as their publisher makes them.
- Only the front display is drawn on.
- The bar's own clock decides `display_until` and the countdowns. It keeps
  network time, so this matters only if its clock is off.
