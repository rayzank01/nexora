# Nexora

One public, self-hosted Telegram bot with independent administration for each group,
interactive setup, group moderation, verification, community analytics,
channel publishing, Telegraph articles and private support. This is a new standalone
project; it does not depend on an existing Telegram bot repository.

**Source repository:** [rayzank01/nexora](https://github.com/rayzank01/nexora).
This source release contains the 27 September expansion, documentation and 174 tests.
The downloadable folder/ZIP mirrors the released source. Deployment remains pending. See the [complete feature/setup audit](docs/EXPANSION.md).
Implemented project with mock-based tests. No real bot token is included, no live
Telegram actions have been tested, and no hosting deployment has been performed.
Register the display name **Nexora** with BotFather; its unique bot
username depends on Telegram availability.

See [packages, refunds and owner advertising](docs/PACKAGES.md) for the new Pro bundle,
Ultra subscription, group list and free-group campaigns. Checkout remains disabled
until exact Stars amounts and private host settings are provided.

## Start on Windows

Requires Python 3.11 or newer with pip. Development verification used Python 3.14.7.

1. Extract the ZIP, then open a terminal in the `nexora` folder containing this README.
2. Create a bot in Telegram using the official **@BotFather** and `/newbot`.
3. Copy `.env.example` to `.env`. Enter your token **locally in that file**. Never put
   it in chat, GitHub, screenshots, support messages or command examples.
4. Install and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env  # only if you have not created .env yet
# Edit .env privately before continuing.
.\.venv\Scripts\python.exe -m nexora
```

On later runs, `./start.ps1` starts the configured bot. It creates an environment and
installs dependencies only if the environment is missing. If PowerShell policy blocks
the script, use the Python command above; changing system execution policy is unnecessary.

## Start on Linux/macOS

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env privately.
python -m nexora
```

Run exactly **one instance** per token/database. The process holds a database instance
lock. Use local disk for SQLite, not a network share. This deployment uses long polling;
an existing webhook causes startup to stop rather than silently remove it.

## Free hosting decision

**Do not deploy this SQLite/polling build unchanged on Render Free.** The
[free-hosting guide](docs/FREE_HOSTING.md) compares the verified provider constraints and
a zero-hosting-fee VM candidate. Local safeguards now stop an unsafe Render startup before
creating a database or contacting Telegram. An optional Linux service configuration and
worker-readiness endpoint are included; no cloud resource or live bot has been started.
The hosting choice is awaiting the user, and no delayed/missed scheduling behavior has
been accepted on their behalf.

## First group setup

Add Nexora as administrator in a **supergroup** and grant delete messages, restrict
members, invite users and pin messages. Send `/setup` to inspect its rights. Keep the
bot an administrator so it can observe normal messages; Telegram privacy and update
delivery determine what it receives.

```text
/set language "en"
/set rules "Be respectful. No advertising or spam."
/set captcha "button"
/set warn_limit 3
/set warn_action "mute"
/set action_seconds 3600
/lock links
/settings
```

Most moderation commands accept a replied-to message or a numeric Telegram user ID.
Usernames are usable in content filters, but cannot reliably identify arbitrary users
for moderation. Custom Nexora roles do not grant Telegram administrator status.

Messages, warning rules, new-member locks and flooding thresholds have working defaults.
CAPTCHA and CAS reputation checking are **off** until enabled. New observed members have
links and media restricted by deletion for five minutes by default; change
`new_user_seconds` or `new_user_locks` to suit your group.

## Dashboard and web verification

In a **private conversation** with Nexora, send `/dashboard -1001234567890` using your
group ID. The bot checks your current admin status and returns a one-hour dashboard
link scoped to that group. The dashboard shows activity, a weekly heatmap, growth,
member activity, reports, moderation history and jobs. It can edit group settings.
Its API also exposes guarded moderation and scheduled-post cancellation endpoints.

The local dashboard is at `http://127.0.0.1:8080`. For access from another device or web
CAPTCHA, configure an HTTPS reverse proxy and `PUBLIC_URL`. Set the three Turnstile
variables before `/set captcha "turnstile"`. See [deployment](docs/DEPLOYMENT.md).
Do not share private dashboard or verification links.

## Publishing and support

For publishing, add Nexora as a channel administrator with post/edit rights. In private:

```text
/channel -1001234567890
/draft launch <b>Welcome to Nexora</b>
/preview launch
/schedule launch 2026-12-01T09:00:00+00:00 every=1d silent
/jobs
```

The date is an example; use a future time. Reply to photos, videos, documents or other
messages with `/draft name` to import media. `/publish name` queues immediate delivery;
both immediate and scheduled publications re-check your Telegram permissions at send time.

For support, create a **private staff group**, set `SUPPORT_CHAT_ID` and numeric
`SUPPORT_ADMIN_IDS`, and restart Nexora. Only put authorized support staff in that group:
all group members can read copied tickets. A user must open the bot and send `/support`
before their messages are relayed. Staff reply to a ticket header or copied message in
the staff group. Support-team broadcasts reach only users who explicitly chose `/subscribe`.

## Super-admin broadcasts

Set your numeric Telegram ID in `SUPER_ADMIN_IDS` privately on the host, then restart.
Send `/myid` privately to the running bot to see your ID. This role is separate from
group administrators and support staff; leave the environment value empty to disable it.

```text
/superadmin
/announce all Nexora service announcement
/announce_send CAMPAIGN_ID CONFIRM
/announce_status CAMPAIGN_ID
```

Choose `users`, `groups` or `all`; reply to media with `/announce all` for attachments.
The bot previews the content and eligible recipient count before anything is queued.
`/announce_cancel CAMPAIGN_ID` cancels remaining deliveries. Group delivery requires
Nexora to still be an admin. Service announcements can reach observed private users who
have contacted the bot and have not used `/unsubscribe`; `/start` explains this, and
`/subscribe` opts back in. Support marketing/news broadcasts retain explicit opt-in.
Telegram does not provide a complete historical subscriber/group directory, so recipients
are registered as the bot receives their messages or group membership updates.

## Verify locally

```sh
python -m unittest discover -s tests -v
python -m compileall -q nexora
```

Tests use a fake Telegram transport and mocked CAS, Turnstile and Telegraph responses.
HTTP integration tests use localhost only. They require no token and do not publish,
contact real people, or moderate real members. See [verification notes](docs/VERIFICATION.md).

## Project guide

| File | Purpose |
|---|---|
| `nexora/engine.py` | Commands, moderation, CAPTCHA, publishing, support and scheduler |
| `nexora/storage.py` | SQLite persistence, deduplication and chat migration |
| `nexora/transport.py` | Telegram and third-party HTTP transport, sanitized errors |
| `nexora/web.py`, `dashboard.html` | Scoped dashboard, API and web verification |
| `nexora/maintenance.py` | Read-only diagnostics and consistent backups |
| `nexora/preflight.py`, `health.py` | Offline hosting checks and worker readiness |
| `deploy/nexora.service` | Optional Linux service for a reviewed always-on host |
| `tests/` | Security and behavior regression tests |
| [COMMANDS](docs/COMMANDS.md) | Complete command syntax and configuration |
| [FEATURES](docs/FEATURES.md) | Reference feature coverage and actual limits |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | Docker, HTTPS, storage, recovery, credentials |
| [FREE HOSTING](docs/FREE_HOSTING.md) | Current free-plan limits and unresolved host decision |
| [SOURCES](docs/SOURCES.md) | Official documentation checked during construction |

Keep `.env`, database files and backups private; `.gitignore` excludes them.
Publishing source does not activate or deploy the Telegram bot.
