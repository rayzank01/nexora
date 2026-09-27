# Verification record

## Public bot expansion — 2026-09-27

**155 local automated tests passed** on Windows/Python 3.14, preserving all 88 prior
regressions and adding 67 expansion/public-bot/final-review checks. See the
[14-feature evidence matrix](EXPANSION.md) for behavior and test names.

Browser QA used a temporary local database with fake Telegram only: settings preview
and confirmation, independent group settings, English/Malayalam menus/options/accessible
labels, weekday headings, and moving a calendar post to a new date/time were verified.
The final browser showed no console errors. The preview was stopped after review.
Python compilation, source manifest and ZIP integrity were checked for this release.
No live Telegram actions, customer messages, customer payments, Docker run, cloud
deployment were performed during verification. Publication is a separate release step;
the 27 September release updates the prior GitHub baseline. The approved Render plan is preserved.


## Super-admin broadcast follow-up — 2026-09-17

88 local tests passed: the prior 75 plus 13 campaign tests covering role separation,
private-only console access, preview without queued messages, confirmation and expiry,
duplicate-confirmation protection, campaign ownership, user/group delivery, opt-out,
revoked bot permissions, revoked operator access, cancellation and delivery reports.
All Telegram delivery was mocked; no live announcement was sent. Public source publication
is separate from activation. Render deployment still requires a compatible hosting plan
and privately configured bot credentials.

## Hosting preparation follow-up — 2026-09-14

**75 local automated tests passed** after the hosting changes: the original 61 behavior
and security tests plus 14 hosting/readiness tests. The new tests cover ordinary local
startup compatibility, stopping Render startup before storage/network operations,
real-mount requirements, path containment/traversal, explicit free-profile rejection,
unsupported database URL rejection without revealing credentials, memory/URI rejection,
port precedence, valid retention/port bounds, side-effect-free offline checks, independent
worker freshness and HTTP readiness while the worker database lock is unavailable.

The original scheduler and CAPTCHA behavior tests still pass. Scheduling semantics were
not changed to accommodate a sleeping service. Official hosting documentation was checked
and the decision is recorded in [FREE HOSTING](FREE_HOSTING.md).

Python compilation and offline preflight checks passed. The Render Free preflight
intentionally exits 2 (incompatible), while the always-on profile exits 0 and explicitly
does not claim account/cost/deployment verification. Both make no external calls.

Docker could not be built/run here because its daemon is unavailable; the Linux service
could not be executed/verified by systemd in this Windows environment. Those files are
reviewable deployment preparation, not a tested cloud deployment. The 2026-09-13 visual
dashboard review below remains the visual baseline; the visible dashboard layout was
unchanged by this follow-up. No live Telegram messages, deployments, paid resources or
GitHub changes occurred in this follow-up.

## Original build — 2026-09-13

Local verification on 2026-09-13, Windows, Python 3.14.7; Pillow 12.3.0 and tzdata 2026.3.

- **61 automated tests passed.** `python -m unittest discover -s tests -q`.
- Python modules compiled successfully.
- A real localhost HTTP server test checked authentication, settings updates, chat scope,
  revocation and security response headers, with Telegram mocked.
- Dashboard opened successfully in the in-app browser with synthetic data. Visual review
  confirmed readable cards, activity chart and settings layout. No real group data used.
- The temporary preview used an in-memory database and was stopped after review.

## Tested behavior

Permission denial, native/bot rights, cross-chat role and note isolation, departed role
holders, administrator protection, short-duration rejection, timed bans, default permission
restoration, expired warnings, warning escalation, word/domain/glob/content matching,
hidden links, command-path locks, multi-action rules, flooding, profile escaping,
media file-ID reuse, CAPTCHA user binding/replay/attempt limits/image generation/timeout,
prior restriction restoration, newer moderation superseding verification, join-request
approval, Turnstile hostname/success paths, CAS opt-in/positive lookup, dashboard token
forgery/revocation, scheduled permission revocation, database reopen/restart scheduling,
uncertain sends, rate-limit deferral, missed interval skipping, DST ambiguity rejection,
support attachment copy/reply identity/chat isolation, opt-out before broadcast delivery,
duplicate update suppression, anonymous command rejection, group/publishing migration,
scoped activity, XP cooldown, self-vote rejection, federation ownership/departure/local-ban
preservation, Telegraph account/page editing and HTTP API authorization.

## What this does not establish

No token was supplied and **no live Telegram bot was started**. Telegram method behavior,
Cloudflare widget completion, CAS uptime and live Telegraph publishing still need a
controlled test group/account after private setup. The Docker image was not built here.
This is not a penetration test, distributed-load benchmark, independent security audit,
or a guarantee of production reliability. The standard unit-test fake does not emulate
every Telegram service edge case. Review failed/uncertain jobs rather than assuming
that every remote action succeeded.

## Suggested first live acceptance checks

After the user configures the token privately, use an isolated test supergroup and an
explicitly authorized test channel/support group. Verify `/setup`, one saved-media reply,
one reversible temporary mute, CAPTCHA completion and expiry, a private preview, a
scheduled test post, a support round trip and unsubscribe-before-broadcast behavior.
These actions were **not** performed during construction. Confirm the intended test
accounts and destinations before conducting them.
