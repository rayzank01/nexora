# Coverage of the supplied feature reference

Updated 27 September: all 14 additions and public group onboarding are mapped to
runnable workflows/tests in [Expansion audit](EXPANSION.md). Billing remains disabled.

This matrix groups repeated features from `group help.txt`, including the duplicate
Rose entry. It describes this implementation rather than claiming compatibility with
another service's private backend. “Implemented” means real executable behavior with
local testing; deployment credentials and Telegram rights still apply.

| Requested area | Delivered implementation | Coverage / constraints |
|---|---|---|
| Welcome, goodbye, rules, help | Per-chat HTML text, media notes, variables, TTL cleanup, `/rules`, `/setup`, `/help` | Implemented; English/Malayalam catalogs for application menus, controls and errors; user content/technical exports retain original form |
| Warnings, timed warnings, escalation | Persisted expiry, threshold action, reset/remove, reason logs | Implemented; moderation actions need bot privileges |
| Mute/ban/kick/unban/restrict | Reply/ID commands, timed actions, native permissions/default restoration | Implemented; group restrictions require supergroups |
| Roles/custom permissions | Native rights and per-chat capability grants | Implemented; Nexora roles do not promote native Telegram administrators |
| Every listed content lock | Links, media, stickers, GIF/animation, video, audio, voice, files, contact, location, poll, forward plus additional field locks | Implemented; based on received Telegram payloads |
| Words/phrases/domains/users/patterns | Case-insensitive rule matching, hidden links, user ID/name, bounded glob patterns | Implemented; arbitrary regex intentionally replaced by safe glob syntax |
| Multi-action rules | Ordered delete/warn/mute/ban/kick/reply | Implemented; admin/trusted exemptions prevent automated punishment |
| Notes and custom commands | Text/media storage, named retrieval, command aliases | Implemented; unsupported copy-protected content remains subject to Telegram errors |
| Media automatic replies | Reusable Telegram file IDs, copied attachments, templates | Implemented; photo/video album publishing added; saved automatic replies retain individual media behavior |
| Admin/user/bot filter audience | Audience selector and explicit bot opt-in | Implemented; only messages Telegram actually delivers can trigger |
| Cleanup, purge, pins, invites | Service/greeting deletion, 100-message purge, pin/unpin, expiring join-request links/revoke | Implemented; native platform restrictions apply |
| User status and admin lists | Current Telegram status + observed join/last-seen data | Implemented; no invented account creation date |
| Group migration | Transactional scope/job/event/federation/dashboard/publishing migration | Implemented; conflicting pre-existing destination data stops for review |
| Flood/repeated spam/advertising | Sliding windows, content locks, domain rules, chained actions | Implemented rule-based checks; no proprietary behavioral scam model |
| CAPTCHA variants | Button, private button, response, arithmetic, PNG characters, basic web, Turnstile | Implemented; web requires HTTPS; Turnstile requires its keys |
| Strict verification/timeouts | Pending member mute, deletion, 5 attempts, single-use token, persisted timeout removal | Implemented; transport/permission failures require operator attention |
| Trusted exceptions/new-member rules | Trust list, first-observed-join content restrictions | Implemented; “new account age” is unavailable, not inferred |
| Join requests/private verification | Standard join-request approval/decline and private challenge delivery | Implemented; dedicated guard-bot query protocol not implemented |
| CAS reputation | Opt-in user-ID lookup during join | Implemented integration; external availability/data coverage not guaranteed; failures logged without treating unknown users as banned |
| Shared-ban federations | Explicit membership, owner-controlled bans, durable per-chat jobs, selective reversal | Implemented; not another vendor's private reputation database |
| Reports/moderation logs | Member reports, staff resolution, SQLite audit events, optional log chat | Implemented; group staff can inspect reports |
| Reputation/upvotes/XP | Daily pair vote limit, minute XP cooldown, rankings | Implemented; simple rules, not sybil-proof identity/reputation |
| Message/member analytics | Observed totals, daily counts, active users, user activity, join/leave growth | Implemented within event retention; no historical backfill/full roster |
| Heatmaps/trends/dashboard/API | Timezone-aware weekly heatmap, daily chart, reports/settings/jobs and JSON APIs | Implemented local web dashboard; access is scoped and revalidated |
| Global group/channel rankings | Local group leaderboards and activity only | External global rankings/data are unavailable; no fabricated substitute |
| Announcements/multiple channels | Explicit destination selection, immediate or queued text/media posts | Implemented; each destination checks rights at actual send time |
| Drafts/imports/previews/edits/buttons | Private drafts, reply import, previews, URL buttons, text/media edits, silent send | Implemented; observed photo/video album drafts added; native callbacks drive administration/events |
| Timezones/recurrence/schedule edits | Offset/IANA time conversion, durable UTC interval jobs, cancel/reschedule/snapshot refresh | Implemented; original intervals preserved; additional local-clock weekday recurrence and visual calendar handle DST |
| Telegraph create/edit/manage | Per-operator/destination account, native node JSON content, page list and updates | Implemented; only Nexora-owned pages and command-size content; no unauthorized account import |
| Private support relay/attachments | Explicit sessions, ticket headers/copies, mapped staff replies, close/block/inbox | Implemented; operator inbox and independent community inboxes; assignment, priority, internal notes and response timing |
| Relevant broadcast | Explicit subscriber list, queued media messages, consent recheck | Implemented; starting support or joining a group never implies consent |
| Global super-admin announcements (2026-09-17) | Separate environment-only operator IDs; users/groups/all audience; media preview, confirmation, persistent queue, cancellation and delivery counts | Implemented for observed contacts/groups; private opt-out and live group admin checks; service notices are distinct from opt-in support broadcasts |
| Persistent storage/scheduling | SQLite WAL, inbox dedup, job state, process lock, restart recovery/diagnostics | Implemented for one small/moderate deployment; not a distributed queue |
| Admin onboarding | Telegram setup checklist, complete command guide, scoped settings dashboard | Implemented; BotFather and environment setup remain operator steps |
| Hosting preparation (2026-09-14) | Offline preflight, unsafe Render storage guard, PORT compatibility, independent worker readiness, optional Linux service | Implemented locally; full-feature Render Free remains incompatible; paid Render plan subsequently approved; no Postgres migration, webhook rewrite or live deployment performed |

All requested **categories** have an implementation or an explicit platform/data limit.
There are no placeholder commands pretending to perform unsupported integrations.
This bot does not clone Combot/Rose/Controller/Livegram's infrastructure, proprietary
analytics or undisclosed detection algorithms. Server-side tests cannot establish live
Telegram permission behavior without the user's bot setup; the package makes no live
deployment claim.
