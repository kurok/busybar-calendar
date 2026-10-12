# Setup

1. [Connect to the bar](#connect-to-the-bar)
2. [Add your calendars](#add-your-calendars)
3. [Keep secrets out of files](#keep-secrets-out-of-files)
4. [Check it](#check-it)
5. [Run it as a service](#run-it-as-a-service)
6. [Troubleshooting](#troubleshooting)

## Connect to the bar

There are two ways to reach the bar. They draw exactly the same things.

### Through BUSY Cloud (simplest)

This is the route the bar's Google Calendar integration takes, and it works
from anywhere, with nothing to enable on the bar.

1. In your BUSY account, create an API token and choose **BUSY Bar** under
   **Access scope**.
2. Store it (see [secrets](#keep-secrets-out-of-files)) and give it to
   `[bar]` without an `address`:

```toml
[bar]
token_command = ["security", "find-generic-password", "-s", "busybar-token", "-w"]
```

It is sent as `Authorization: Bearer ...` to `https://api.busy.app/busybar`.

### On the local network

Faster, and does not depend on the cloud, but the bar's HTTP API over Wi-Fi
is **disabled by default**.

1. Connect the bar to your computer by USB and open `http://10.0.4.20`.
2. On the **Network** tab, in **HTTP API**, choose **Set password and
   enable**. Keep the password to **32 characters or fewer**. The firmware
   refuses longer ones.
3. Find the bar's address: **Settings -> Wi-Fi -> your network -> View IP
   Address**.

```toml
[bar]
address = "192.168.1.50"
token_command = ["security", "find-generic-password", "-s", "busybar-lan", "-w"]
```

The password is sent as `X-API-Token`. To check the bar's mode without a
password: `curl http://<address>/api/access` returns `{"mode":"disabled"}`,
`"enabled"` or `"key"`. While it says `disabled`, every other request over
Wi-Fi gets `403 Forbidden`, whatever token you send. Over USB
(`address = "10.0.4.20"`) no password is needed at all.

## Add your calendars

Each `[[sources]]` entry is one CalDAV account or one ICS feed. A CalDAV
account uses all of its calendars unless you [filter them](#choosing-calendars).

### CalDAV

| Provider | `url` | Password |
| --- | --- | --- |
| iCloud | `https://caldav.icloud.com` | an app-specific password (account.apple.com -> Sign-In and Security -> App-Specific Passwords) |
| Fastmail | `https://caldav.fastmail.com` | an app password (Settings -> Privacy & Security) |
| Nextcloud | `https://cloud.example.com/remote.php/dav` | your password, or an app password |
| PrivateEmail (Namecheap) | `https://dav.privateemail.com` | your mailbox password |
| Radicale, Baïkal, Synology, others | the server's root URL, or a calendar's URL | as the server wants it |

`username` is usually your full email address. A root URL is enough when
the server supports discovery (`/.well-known/caldav`); otherwise give the
URL of one calendar, and it is used as it is. Servers that only speak
Digest auth need `auth = "digest"`.

```toml
[[sources]]
name = "iCloud"
type = "caldav"
url = "https://caldav.icloud.com"
username = "me@icloud.com"
password_command = ["security", "find-generic-password", "-s", "busybar-icloud", "-w"]
include = ["Home", "Work"]

[sources.calendars.Work.status]
show = "meeting"
```

### Choosing calendars

`busybar-calendar calendars` lists each calendar on the account with its
**id** (the last part of its URL) and **name**, and marks the ones in use:

```
PrivateEmail (caldav): 22 calendars, 1 used
  * 4711   Doe, Jane
    5001   Ops Maintenances
    5002   Infra Maintenances
    6001   Office - Room 1 (6 people)
    ...
```

Two lists filter them. Each entry is a calendar's **name**, its **id**, or
its **URL**, and may use the wildcards `*` and `?`. Matching is exact and
case-sensitive.

| | |
| --- | --- |
| `include` | Use only these calendars. Without it, all of them. |
| `exclude` | Leave these out, after `include`. |

```toml
include = ["Doe, Jane"]                 # by name
include = ["4711"]                     # by id: survives a rename
include = ["Doe, Jane", "* Maintenances"]
exclude = ["Office - Room *", "Room *"]   # everything except the meeting rooms
```

Organisation accounts often expose shared calendars. A PrivateEmail
business mailbox, for example, lists every meeting room and team calendar
next to your own. With no filter, other people's room bookings would reach
your bar, so name your own calendar under `include`.

Calendars come in the order `include` lists them: when two events start at
the same time, the calendar listed last wins. An entry that matches nothing
is reported, by `calendars` and in the service's log.

Per-calendar settings can be keyed by name or by id, and the id wins when
both are given:

```toml
[sources.calendars."4711".reminder]
minutes_before = 10
```

Invitations you declined are skipped by matching your attendee address. It
defaults to `username` when that is an email address; set `emails = [...]`
if your invitations go to another one.

### ICS / webcal feeds

For calendars that only publish a link. A feed is one calendar, named after
its source. `webcal://` links work as they are.

| Calendar | Where to find the link |
| --- | --- |
| Outlook / Microsoft 365 | Settings -> Calendar -> Shared calendars -> **Publish a calendar** -> ICS link |
| Google Calendar | Settings -> the calendar -> Integrate calendar -> **Secret address in iCal format** |
| Proton Calendar | the calendar's menu -> Share -> **Share with anyone** (link) |

```toml
[[sources]]
name = "Outlook"
type = "ics"
url = "https://outlook.office365.com/owa/calendar/.../calendar.ics"
```

A feed is only as fresh as the provider makes it. Outlook and Google can
take a while to republish a change, while CalDAV sees it on the next poll
(`poll_minutes`, default 5).

## Keep secrets out of files

Every password and token takes one of three forms. Prefer the last two:

```toml
password = "..."                       # inline: only for throwaway testing
password_env = "ICLOUD_APP_PASSWORD"   # an environment variable
password_command = ["security", "find-generic-password", "-s", "busybar-icloud", "-w"]
```

The same goes for the bar: `token`, `token_env`, `token_command`. A command
is run without a shell and its output, stripped, is the secret.

On macOS, store a secret in the Keychain from your own terminal. It prompts,
so the secret ends up neither on screen nor in your shell history:

```sh
security add-generic-password -U -s busybar-icloud -a me@icloud.com -w
```

On Linux, `secret-tool` (libsecret) or `pass` work the same way:
`password_command = ["secret-tool", "lookup", "service", "busybar-icloud"]`.

`config.toml` is in `.gitignore`. Keep it that way even with no secrets in
it, since it names your accounts.

## Check it

```sh
busybar-calendar calendars                 # discovery: calendars per CalDAV source
busybar-calendar upcoming --hours 48       # events, their settings, and what is on now
busybar-calendar demo                      # a sample reminder for 20 seconds
busybar-calendar demo --status --show meeting
busybar-calendar demo --font global --title "Планування спринту"
busybar-calendar -v run                    # run in the foreground with debug logs
```

## Run it as a service

### macOS (launchd)

`~/Library/LaunchAgents/app.busybar.calendar.plist`:

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
  <key>StandardErrorPath</key><string>/tmp/busybar-calendar.log</string>
</dict>
</plist>
```

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/app.busybar.calendar.plist
```

A launch agent runs in your login session, so it can read the login
Keychain.

### Linux (systemd user unit)

`~/.config/systemd/user/busybar-calendar.service`:

```ini
[Unit]
Description=BUSY Bar calendar reminders
After=network-online.target

[Service]
ExecStart=%h/.local/bin/busybar-calendar --config %h/.config/busybar-calendar/config.toml run
Restart=on-failure

[Install]
WantedBy=default.target
```

```sh
systemctl --user enable --now busybar-calendar
```

### Docker

```sh
docker build -t busybar-calendar .
docker run -d --restart unless-stopped \
  -e BUSYBAR_TOKEN -e CALDAV_PASSWORD \
  -v "$PWD/config.toml:/config/config.toml:ro" busybar-calendar
```

In a container, use `token_env` and `password_env`, since the Keychain is
not there.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `403` from the bar on the LAN | The Wi-Fi HTTP API is disabled (`/api/access` says so), the password is wrong, or it is longer than 32 characters. |
| `401` from the bar via the cloud | The token is not a BUSY Bar-scope token, or it was revoked. |
| `check the credentials` from CalDAV | Wrong username or password. iCloud and Fastmail need an app password. |
| `no current-user-principal` | The server has no discovery at that URL: give a calendar's URL instead. |
| An event never shows | It is all-day or 24 hours or longer, marked free (`skip_free`), cancelled, or declined. `upcoming` lists only what will show. |
| `409` in the log | Something above `bar.priority` (default 91) is on screen; it is retried. |
| A reminder shows late | The loop wakes on time; a late reminder means the event arrived late: lower `poll_minutes`, or check the feed's own refresh delay. |
