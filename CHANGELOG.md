# Changelog

All notable changes to busybar-calendar. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Install with one line, no clone needed:
  `uv tool install git+https://github.com/kurok/busybar-calendar`, and
  upgrade with `uv tool upgrade busybar-calendar`.

### Fixed

- `status` no longer offers `restart` as the way to a newer version when the
  service runs from another install (a checkout run with `uv run`, say): a
  restart would start the old version again. It names the install to upgrade,
  and the `uv tool upgrade` command when that install came from git.

## [0.3.1] - 2026-10-12

### Added

- `status` checks the bar with one light read-only call and says whether it
  answers, refuses the token, or does not answer at all - with what to do -
  so a stuck bar no longer looks like a healthy setup.

### Fixed

- Event titles are capped at 120 characters (a longer one only scrolls
  longer). A draw request with a title of thousands of characters left a
  bar's HTTP API hanging, on the LAN and through BUSY Cloud, until the bar
  was power-cycled.

## [0.3.0] - 2026-10-12

### Changed

- `init` and `add` ask for the calendar provider from a list - iCloud,
  Fastmail, PrivateEmail, Nextcloud or another server - guessed from your
  address, instead of for the server's URL; Nextcloud needs only its host.

### Added

- `busybar-calendar` on its own says where you stand: the first steps before
  there is a config, the status after, instead of a usage error.
- `status` shows the version the background service runs, read from the line
  it now logs at start, and says to `restart` when that is not the version
  installed; the setup guide has an "Upgrading" section.
- Tentative events in published feeds, which carry no attendees, now count as
  tentative: Outlook's busy status or `STATUS:TENTATIVE` decides there, for
  overlaps and for `status.tentative`.

### Fixed

- A Keychain / libsecret prompt that failed - a mistyped retype - ended
  `init` and `add` with a traceback; it is now asked again, up to three times,
  then reported in one line.
- A failing `launchctl` or `systemctl` ended `install` with a traceback; it is
  now one line naming the command and its exit code.
- The service remembered every screen it had chimed for; it now forgets
  them once their events are gone, so a long-running service does not grow.
- A mistyped `sync.timezone` ended every command in a traceback; it is now
  rejected when the config is read, with an example of a valid name.
- `calendars` and `replay` ended in a traceback when a calendar server could
  not be reached; they now say which address and why.
- A config mistake printed pydantic's whole report; it is now one line per
  problem, naming the key (`bar.adress: Extra inputs are not permitted`), in
  the CLI and in `app.py` alike.
- `app.py --minutes 0` (and other invalid reminder or status settings given
  as flags) was accepted and only failed at the first event; it now fails at
  start.

## [0.2.0] - 2026-10-12

### Added

- `busybar-calendar add`: another calendar source by the same questions as
  `init`, appended to the config with its comments and layout kept, under a
  name that does not clash with the others.
- `--json` for `status` and `check`: the service, the screen now and next,
  and each check's finding with its fields (firmware, calendars, next event),
  with times in ISO 8601.
- `busybar-calendar restart`, for the background service after a new
  password or config.
- [docs/troubleshooting.md](docs/troubleshooting.md): what `check` and
  `status` say for each common problem, from real failures, and the fix.

### Changed

- After `init` or `add`, an installed background service is restarted, so it
  reads the new config.
- `init` and `add` keep each account's password in a Keychain / libsecret
  entry of its own; two accounts on one domain no longer share one.

### Fixed

- `check` called a BUSY Cloud that refused the token "unreachable"; it now
  says the token is wrong, revoked or lacks the BUSY Bar scope.
- For a source whose `include` matched no calendar, `check` added a
  reassuring "no events in the next 7 days"; it now lists the calendars
  there are, and the source's own warnings no longer repeat in its output.

## [0.1.0] - 2026-10-12

The first release.

### Added

- Reminders and a BUSY status on the BUSY Bar from any CalDAV account
  (iCloud, Fastmail, Nextcloud, PrivateEmail, Radicale, ...) or ICS / webcal
  link, drawn through the bar's HTTP API on the LAN or through BUSY Cloud.
- The Google Calendar integration's per-calendar settings - reminder time,
  sound, show name, status during events - layered as defaults, per source
  and per calendar.
- A red calendar icon and a red BUSY beside the countdown during an event;
  the bar's own animations and statuses (`meeting`, `on_call`, ...) as
  options.
- Overlapping events settled by your response: accepted over tentative over
  not answered, then the newest event. `status.tentative` keeps tentative
  events off the busy status.
- Calendar filters: `include` / `exclude` by name, id or URL, with wildcards.
- Commands: `init` (a few questions write the config, passwords go to the
  Keychain or libsecret), `check` (the bar, its token and every calendar),
  `install` / `uninstall` (launchd or systemd), `status` (running? now and
  next), `calendars`, `upcoming`, `demo`, `replay`, `run`, `--version`.
- `app.py`, following the BUSY Bar community gallery's rules: `--host`,
  `--ics`, `--caldav`, `--demo`, `--test`, secrets from the environment.
- Docs with screenshots read back from a real bar, and a configuration
  reference generated from the code.

### Fixed

Found on a bar running firmware 1.2.4, and recorded in
[docs/how-it-works.md](docs/how-it-works.md):

- The countdown overlapped the title: its font sits 4px high in its box.
- The status lost its icon when it replaced a reminder as the reminder's
  `display_until` fired; drawings now outlive their screen by a minute.
- A draw merges by element id, so a new layout could land on top of the old
  one; a clear now comes first only when an element would be left over,
  and a reminder becomes its event without a blink.
- CalDAV discovery turned PROPFIND into GET on a 302 redirect.
- A 401 or 404 from a calendar was retried forever; it now stops the
  service with the reason.
- A refused draw (409) stopped the demo and replay.
- A Ctrl-C during the slow first start printed a traceback.

[Unreleased]: https://github.com/kurok/busybar-calendar/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/kurok/busybar-calendar/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/kurok/busybar-calendar/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kurok/busybar-calendar/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kurok/busybar-calendar/releases/tag/v0.1.0
