> Historical free-hosting analysis. Superseded by the user’s later approval of the
> Render $7.25/month base configuration. No live deployment occurred. See
> [current deployment setup](DEPLOYMENT.md).

# Free hosting: a decision is still required

Checked against official documentation on **2026-09-14**. No hosting account was created,
no service was deployed, no paid resources were provisioned, and no bot token was used.
The source is provided on GitHub and in the delivered ZIP; publication does not deploy it.

Nexora's existing design requires a running poller, a running scheduler and durable
SQLite storage. The bot has not been converted to a reduced-feature webhook service.
The startup guard now prevents accidentally treating a disposable Render filesystem as
durable storage. No scheduler, CAPTCHA or moderation policy was weakened.

## What each choice actually provides

| Choice | Hosting cost | Full existing behavior | Remaining requirement |
|---|---|---|---|
| Render Free, unchanged Nexora | Free within applicable allowances | **No**; unsafe persistence and sleeping worker | Do not deploy this build there |
| Render Free + external Postgres + webhook rewrite | Potentially free within both providers' quotas | **No equivalence**; storage alone cannot run sleeping timers | User must first choose acceptable timing/feature changes; not implemented |
| Oracle Always Free eligible VM + durable boot disk | No hosting fee while all resources remain within account allowances | Existing worker/storage architecture can run intact | User approval to change host; account eligibility, capacity, private setup and backups |
| Existing computer left on | No new cloud-hosting bill | Works while it stays awake and connected | Electricity/internet costs and computer uptime remain; optional web verification still needs public HTTPS |

**No option here promises uninterrupted service forever at zero cost.** The concrete
cloud candidate that preserves the architecture is the eligible free VM. It is not
automatically selected, and availability has not been checked inside a user account.

## Render findings

Render Free web services sleep after 15 minutes without inbound traffic, can lose local
files on restart/redeploy/spin-down, and cannot attach persistent disks. Free Render
Postgres expires after 30 days. Free instance hours are shared per workspace; usage
limits can suspend service or incur overage charges when billing is enabled.
[Official Render free-service documentation](https://render.com/docs/free).

Inference for this implementation: `getUpdates` polling is outbound and does not arrange
an inbound wake-up. A scheduled post or CAPTCHA deadline also creates no incoming HTTP
request. During sleep, deadlines cannot execute. A later wake-up cannot undo a missed
real-time moderation opportunity. Keep-alive pings do not fix durable storage or provide
an availability/free-cost guarantee. A successful HTTP listener alone is not readiness.

Nexora accepts the documented `PORT` setting and Render binding conventions, but this
is **port compatibility, not Free-plan compatibility**. Render detection uses its official
`RENDER=true` variable. [Render environment variables](https://render.com/docs/environment-variables).

## Why a free database alone is insufficient

Neon's official free-plan guide describes durable Postgres with 0.5 GB storage per project,
100 compute-unit hours per month and scale-to-zero. It is an actual free allowance, not
Render's expiring database trial. [Neon free-plan guide](https://neon.com/blog/how-to-make-the-most-of-neons-free-plan).

A future migration would need a real Postgres adapter, schema migration, durable update
deduplication, webhook secret validation and a reliable job executor. This build has
none of those Postgres/webhook changes and now rejects `DATABASE_URL` rather than ignoring
it. A database that retains jobs does not execute the Python worker for us. Continuous
database polling can also consume free compute allowances. An external timer or another
worker must be assessed against CAPTCHA and moderation deadlines, not merely daily posts.

## Concrete zero-hosting-fee VM candidate

Candidate: **one Oracle Always Free-eligible A1 VM, 1 OCPU, 2 GB RAM, one 50 GB boot volume,
in the account's home region**, with an eligible Ubuntu image. The current published A1
allowance is 1,500 OCPU-hours and 9,000 GB-hours/month; combined free boot/block storage is
200 GB. Existing account usage counts toward those totals. Capacity can be unavailable,
and idle instances may be reclaimed. Do not create artificial load to evade idle policy.
[Oracle Always Free resource limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Oracle distinguishes non-expiring Always Free resources from promotional trial credits.
Signup generally requires phone/card verification. Remain on the free account and use
only eligible resources; do not upgrade or select chargeable resources to resolve a
capacity error. [Oracle Free Tier account documentation](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm).

This is a candidate configuration, not verified account capacity or a cost guarantee.
The user must complete provider identity/payment verification privately, inspect the
zero-cost eligibility of the exact resources, and accept the provider terms themselves.
No credit-card details or bot secrets should be sent in chat. If free capacity is absent,
pause; do not silently substitute a paid VM. Account-level quota and bandwidth checks
remain necessary. The app cannot prevent cloud-account billing mistakes.

## Local preparation supplied

The following commands are **offline checks**, not deployment:

```sh
python -m nexora.preflight --profile render-free
# exits 2 with the incompatibility explanation; makes no network requests
python -m nexora.preflight --profile always-on
# reports architectural requirements, not successful provisioning or verified cost
```

Startup rejects memory/connection-string database paths, unused `DATABASE_URL`, invalid
port/retention values, and paths escaping a declared `PERSISTENT_DATA_DIR`. On Render,
that declared root must also be an existing mount. Setting `PERSISTENT_DATA_DIR` to an
ordinary directory does not make it durable. A mount check is a local safeguard, not
proof of a provider's billing plan or uptime. No Render blueprint is supplied that could
accidentally provision paid compute/disks under a zero-cost request.

`/health` reports HTTP liveness. `/ready` returns 200 only when both polling and scheduler
progress are at most 90 seconds old; otherwise it returns 503. It does not take the
worker's database lock and cannot itself wake/advance jobs. Readiness does not prove every
job succeeded; inspect failed/uncertain jobs separately. Docker healthchecks now use it.
An unhealthy status does not automatically recover the machine or restart a Docker
container; these probes are observability, not a keep-alive service.

## Reviewable VM installation path (not executed)

After the host choice and provider setup, either use the existing Docker Compose package
or the optional [Linux service file](../deploy/nexora.service). Do not run both.

For the service-file route, an administrator would:

1. Verify the chosen Ubuntu host has Python 3.11+ with `venv`, durable local disk,
   outbound HTTPS and accurate system time. No inbound Telegram webhook is required.
2. Transfer/extract the **delivered ZIP** or clone the Nexora repository. Place
   the project at `/opt/nexora` and create a dedicated system user/group named `nexora`.
3. Create `/opt/nexora/.venv` and install the project's `requirements.txt`. Keep the
   source/virtualenv readable but not writable by the bot user.
4. Create `/etc/nexora.env` privately with mode 0600, owned by root. Put `BOT_TOKEN`
   and optional support/integration values there. Do **not** copy the relative
   `DATABASE_PATH=data/...` from the desktop example: omit that variable here, or use
   `/var/lib/nexora/nexora.sqlite3`. Environment-file entries can override service defaults.
5. Review/install `deploy/nexora.service` in `/etc/systemd/system/nexora.service` and
   run `systemd-analyze verify` on it. The unit creates `/var/lib/nexora`, keeps it
   writable, restricts other filesystem writes and restarts failed processes. Provider
   termination is outside its control. Service directives were checked against the
   [systemd execution reference](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.exec.xml)
   and [service reference](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.service.xml).
6. Only after private configuration and authorization for activation, reload systemd
   and enable/start the service. Check `/ready` and perform the controlled Telegram
   acceptance tests in [VERIFICATION](VERIFICATION.md). No such live tests were run here.

The listener remains localhost-only. For a private admin dashboard, an SSH tunnel to
port 8080 is sufficient. Web/Turnstile verification for joining users still requires a
public HTTPS origin and private Turnstile setup if chosen; this optional integration is
not claimed complete by starting a VM. Keep group/private CAPTCHA modes available rather
than pretending a localhost link works for members. Use a hostname already owned by the
user or assess an approved no-cost HTTPS option separately; no domain purchase is assumed.

Back up SQLite with the included maintenance command, transfer encrypted/private backups
off the VM, and periodically test restoration. A persistent boot disk survives ordinary
process restarts but is not protection against provider reclamation, deletion or account
loss. A recreated worker must restore the same database before polling resumes.

## Decision to make next

May we prepare the Oracle Always Free candidate instead of Render, accepting eligibility,
capacity and reclamation constraints while preserving Nexora's worker architecture?
If Render Free must remain, first decide exactly which timing changes are acceptable;
that decision has **not** been inferred from the zero-cost requirement or from silence.
No secrets or payment details are needed to answer this question.
