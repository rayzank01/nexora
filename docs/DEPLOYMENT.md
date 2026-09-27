# Deployment and operations

**Current hosting decision:** the user approved Render's $7.25/month base configuration
($7 compute plus a 1 GB disk) in the prior hosting session. This is the recorded approval,
not a fresh price quotation. No live service has been deployed. Preserve the mounted disk
at `/app/data`, `DATABASE_PATH=/app/data/nexora.sqlite3` and
`PERSISTENT_DATA_DIR=/app/data`. Set the bot token and numeric super-admin IDs privately;
set the public HTTPS origin once Render supplies it. `/health` is the liveness path;
monitor `/ready` separately. The free-plan discussion is historical, not the current choice.

Deploy the 27 September expanded source release from GitHub. [Expansion operations](EXPANSION.md) covers public onboarding, backups/restore,
privacy, optional AI and disabled billing. No additional paid service was selected.

## Architecture

Python 3.11+, standard-library HTTP/SQLite, Pillow for PNG CAPTCHA, tzdata for portable
IANA zones. One long-polling worker processes updates and jobs; the HTTP server shares
a reentrant lock with it. Remote calls may delay other operations, so this is intended
for a small or moderate self-hosted community, not thousands of busy groups. There is
no external Redis, database server or paid platform requirement.

`HTTP_PORT` takes precedence over `PORT`; on Render the default bind is `0.0.0.0` and
the default port is 10000, while desktop defaults stay localhost:8080. Port compatibility
does not remove hosting limitations. `PERSISTENT_DATA_DIR`, when specified, must contain
the resolved database file. Render additionally requires that root to be a real mount.
`DATABASE_URL` is rejected because this version has no remote Postgres adapter.

`data/nexora.sqlite3` contains chat configuration, roles, moderation data, job payloads,
support ticket mappings, private publishing drafts and Telegraph access tokens. Treat
the database and backups as secrets. SQLite is not encrypted at rest; use OS disk
encryption and owner-only file permissions. On Windows, restrict the folder ACL to the
service account. The process sets owner-only permissions where supported by the OS.

## Docker

```sh
cp .env.example .env
# Configure .env privately.
docker compose up --build -d
docker compose logs --tail=50
```

The image runs as UID 10001, uses a named persistent volume, drops Linux capabilities and
exposes HTTP on localhost only. Compose explicitly overrides `HTTP_HOST` for the container.
The Docker configuration is supplied but was not built on the delivery machine. Validate
it on your hosting environment before production use. Do not run the host Python worker
alongside the container with the same token. Do not commit `.env` or database volumes.

## HTTPS and optional integrations

Put the HTTP listener behind a maintained HTTPS reverse proxy (for example Caddy or
nginx). Forward only the Nexora hostname to `127.0.0.1:8080`. Configure request-body limits,
connection/read timeouts and modest per-IP limits; do not log verification query strings.
Keep the listener private if only using the dashboard locally. `PUBLIC_URL` is the public
HTTPS **origin**, without path/trailing slash. Expose it only after TLS is working.

Turnstile needs a Cloudflare widget with your exact host registered, `TURNSTILE_SITE_KEY`,
`TURNSTILE_SECRET`, and `TURNSTILE_HOSTNAME`. Nexora validates the response on the server,
requires action `nexora`, and verifies hostname. Set `/set captcha "turnstile"` per group
only after environment configuration. The basic `web` mode is a simple response challenge,
not equivalent to Turnstile. External service failure never counts as successful verification.

CAS needs no bundled API key. `/set cas true` enables it per group and sends joining
numeric IDs to the CAS service. An unavailable lookup is recorded and ordinary verification
continues. This opt-in integration does not promise complete or correct reputation data.

Telegraph creates a separate managed account for each operator/destination on first use.
Its access token is stored in SQLite. Image/embed URLs in article nodes must be publicly
usable by Telegraph. No external content is fetched by Nexora from arbitrary article URLs.

## API authentication

Issue a token by sending `/dashboard CHAT_ID` privately. It expires in one hour, is
stored hashed in SQLite. Legacy stats/settings/moderation endpoints remain scoped to
that initial chat. The new groups/console endpoints allow selecting another known group
only after independently verifying the same user's live native admin rights there. Every
request also revalidates the original session group; revocation there expires its access. Tokens are URL fragments in dashboard links, then removed from the address bar
and kept in browser session storage. Requests use `Authorization: Bearer TOKEN`.

| Endpoint | Method / behavior |
|---|---|
| `/health` | GET; unauthenticated process/listener liveness, not proof Telegram polling is healthy |
| `/ready` | GET; 200 when polling and scheduler each progressed within 90 seconds, otherwise 503 |
| `/api/groups`, `/api/console`, `/api/personal` | Authenticated group selector, scoped interactive controls and own-data export; console POST requires preview then bound confirmation |
| `/api/stats` | GET; activity, daily growth, heatmap, recent logs and job states |
| `/api/settings` | GET settings; POST `{"key":"warn_limit","value":3}` |
| `/api/reports` | GET scoped report records |
| `/api/moderate` | POST `{"user":123,"action":"mute","seconds":3600,"reason":"spam"}` |
| `/api/cancel` | POST `{"job":123}`; cancels a pending publishing job in the token's chat |

The dashboard UI edits settings and displays reports/analytics/jobs; the moderation and
cancellation API endpoints are available for external admin clients. API requests require
the bearer header, have no wildcard CORS permission, and do not authenticate via cookies.
The public verification endpoint instead uses a short-lived, single-use private challenge
capability. Treat possession of that link as sensitive. Sign-out clears browser storage;
issued tokens naturally expire within an hour.

## Delivery and recovery semantics

Incoming updates are persisted before the next polling offset is committed. Each update
ID is processed once in normal operation. Pending rows resume after restart. Interrupted,
failed or uncertain rows are retained as diagnostic states instead of being automatically
replayed into duplicate moderator actions or replies.

Jobs are persisted with status `pending`, `running`, `done`, `cancelled`, `failed` or
`uncertain`. A crash after remote delivery but before SQLite commit can be ambiguous:
Telegram does not provide an application idempotency key for these sends. Therefore
interrupted sends and network timeouts become **uncertain**, never automatically resent.
Definite 429 responses honor the supplied retry delay. Other failed jobs need review.
Recurring jobs skip missed intervals after downtime; they do not spam missed repetitions.
Anti-flood windows are in memory and reset on process restart; warnings/roles/jobs persist.

```sh
python -m nexora.maintenance status
python -m nexora.maintenance backup backups/nexora-2026-12-01.sqlite3
```

The backup command uses SQLite's backup API and refuses to overwrite an existing backup.
Never copy only the main database file while WAL writes are active. Restore by stopping
Nexora, preserving the current data directory, and replacing it with the verified backup.
Keep backups out of the GitHub repository.

Inspect Telegram and the job's database record before manually retrying an uncertain
publication. To resend, use a new `/publish` or `/schedule` command after confirming the
previous message was not delivered. There is deliberately no one-click automatic replay
of ambiguous moderation/support updates. If kick succeeds at ban but unban fails, inspect
the member and use `/unban` explicitly after restoring permissions.

## Retention and privacy

`RETENTION_DAYS` controls activity/moderation events (default 90 days). Hourly cleanup
removes expired events and dashboard tokens, clears failed/uncertain update payloads,
and trims older completed update IDs. Completed updates immediately discard their bodies.
Pending updates retain their payload until processed; investigate a backlog promptly.
Ticket metadata, staff reply mappings, saved notes, templates, member observations,
warning lists, scores, subscriptions, job payloads and Telegraph tokens persist until
administratively removed. Analytics activity counts use the event window, while XP and
reputation are persistent totals. This is not a promise of automatic erasure of every
user record after 90 days.

Support content itself is copied to Telegram staff chats and remains subject to Telegram
and staff retention. Limit membership of the staff chat. Nexora does not put user message
bodies or credential-bearing request URLs in application logs. Bot token rotation happens
through BotFather followed by a private environment update and restart.

## Source control

The source repository is [rayzank01/nexora](https://github.com/rayzank01/nexora).
It contains the source, documentation and tests. Repository publication does not mean
a live hosting deployment has been completed.
Before future pushes, run the local test suite, inspect the source diff and keep only
intended source files. The ZIP and folder delivered here contain no real secrets.
Never upload `.env`, runtime databases, backups or virtual environments. Repository
publication is separate from live Telegram deployment.
