# Commands and configuration

New package/owner commands: `/plans`, `/buypro`, `/buyultra`, `/assignplan`,
`/operator_groups`, `/advertise`. Updated `/subscriptions` cancels/refunds under the
seven-day policy. See [complete package guide](PACKAGES.md).


Commands remain English identifiers. Bot menus, web controls, verification and application
errors use English/Malayalam catalogs. Set the group language in `/panel` or with
`/set language "ml"`; use `/language ml` privately for personal menus. User-authored
content and technical exports keep their original representation.

## Interactive additions (27 September)

| Entry | Behavior |
|---|---|
| `/panel [GROUP_ID]`, `/wizard`, `/setup` | Interactive administration; private group selector or current group/topic |
| `/language en` or `/language ml` | Personal private language |
| `/appeal GROUP_ID`, `/appeals GROUP_ID` | Private member appeal and native admin review |
| `/test SAMPLE` | Side-effect-free rule explanation; also supports a replied sample |
| `/privacy` | Private personal export, deletion and AI capture opt-out |
| `/csupport GROUP_ID`, `/cticket GROUP_ID ID` | Community-specific private support and staff ticket controls |
| `/ticket ID` | Operator support assignment, priority, internal notes and close |
| `/album NAME` | Private: reply to an observed photo/video album after selecting `/channel` |
| `/faq QUESTION` | Group-approved optional AI FAQ |
| `/backups` | Private super-admin backup status |
| `/plan GROUP_ID`, `/upgrade GROUP_ID` | Group plan and disabled-by-default invoice workflow |
| `/subscriptions`, `/terms`, `/paysupport` | Payer renewal cancellation, configured terms and support |
| `/refund CHARGE_ID` | Private super-admin refund confirmation; only for configured billing |

The panel also contains raid, name-alert, templates/bulk, topic, event/poll/quiz,
recurrence, retention and optional AI controls. See [Expansion setup](EXPANSION.md)
for formats, permissions, tests and operating limits.

## Group permissions

Native Telegram admins can configure Nexora. Moderation, deletion, invitations, pins and
channel publishing also require the corresponding native right. The bot checks its own
rights before privileged operations. A numeric user ID is required unless replying to a
member's message. Anonymous `sender_chat` commands are deliberately ignored; use a visible
admin identity. Custom role grants are scoped to a single chat and inactive for departed
members. Existing native admins and Nexora itself are protected from punishment.

| Command | Syntax / behavior |
|---|---|
| `/setup`, `/settings` | Interactive setup / complete current settings |
| `/set` | `/set KEY JSON_VALUE`, one setting at a time |
| `/role` | `/role USER_ID moderate,delete,reports`; native admins only |
| `/unrole` | `/unrole USER_ID`; removes all custom capabilities |
| `/warn` | `/warn USER_ID [2h] reason`; optional warning expiry |
| `/warnings` | `/warnings [USER_ID]`; only unexpired warnings |
| `/unwarn`, `/resetwarns` | Remove last warning / all warnings for a member |
| `/mute`, `/ban` | `/mute USER_ID 1h reason`; omit duration for indefinite action |
| `/kick` | Ban then unban to remove a member while allowing later re-entry |
| `/unmute`, `/unban` | Restore chat defaults / remove ban |
| `/restrict` | `/restrict USER_ID 1h {"can_send_messages":true,"can_send_photos":false}` |
| `/trust`, `/untrust` | Native admins: bypass automated moderation/verification for a member |
| `/verify` | Manually complete that member's current CAPTCHA |
| `/delete` | Reply to one message |
| `/purge` | Reply to first message; deletes through the command, max 100 IDs |
| `/pin`, `/unpin` | Reply to a message; requires bot pin permission |
| `/invite` | `/invite 1d`: time-limited join-request invite |
| `/revoke` | `/revoke BOT_CREATED_INVITE_URL` |
| `/info`, `/admins`, `/rules` | Member observation/status, admin list, rules |
| `/stats`, `/leaderboard`, `/rep` | Activity totals, XP ranking, reputation ranking |
| `/upvote` | Reply to another member, or `/upvote USER_ID`; once per pair per day |
| `/report` | Reply to a message with `/report reason`, or `/report USER_ID reason` |
| `/reports`, `/resolve` | Staff report inbox; `/resolve REPORT_ID` marks resolved |

Custom capabilities: `moderate`, `delete`, `pin`, `invite`, `config`, `publish`, `reports`.
`config` can change automated punishment policies and notes; grant it only to trusted
staff. It does not allow granting roles. Publishing and dashboard access require native
admin access regardless of a custom role. Roles manage Nexora privileges, not Telegram
administrator promotion/demotion.

Timed mute/ban/restrict durations are 60 seconds through 365 days. `0` is indefinite.
Warnings can expire independently; escalation clears the warning list after a successful
configured action. Failed actions stay in the local diagnostics database for inspection.

## Settings

Run `/settings` for all values. JSON strings need double quotes.

| Setting | Values / purpose |
|---|---|
| `language` | `"en"` or `"ml"` |
| `rules`, `help` | Text; rules accept Telegram HTML |
| `welcome`, `goodbye` | HTML templates; empty string disables text greeting |
| `greeting_ttl` | Seconds until greeting deletion; `0` keeps it |
| `cleanup_service` | Delete join/leave notifications, `true` / `false` |
| `locks` | Array of content-type names; `/lock` and `/unlock` are shortcuts |
| `warn_limit`, `warn_ttl` | Threshold count and default warning expiry seconds |
| `warn_action` | `"mute"`, `"ban"`, `"kick"` |
| `action_seconds` | 60–86400 seconds for automated punishment |
| `flood_count`, `flood_window` | Max observed messages in the sliding window |
| `repeat_count` | Equal-content threshold within that window |
| `captcha` | `"off"`, `"button"`, `"response"`, `"math"`, `"image"`, `"private"`, `"web"`, `"turnstile"` |
| `captcha_seconds` | 60–86400 seconds to complete verification |
| `captcha_text` | Group verification prompt with template variables |
| `strict` | Delete incoming messages from pending unverified members |
| `new_user_seconds` | Period for new observed member content restrictions |
| `new_user_locks` | Default `["links","media"]`; set `[]` to disable |
| `cas` | Opt-in check of joining user's ID against CAS |
| `timezone` | IANA zone, e.g. `"Europe/London"` or `"Asia/Kolkata"` |
| `log_chat` | Numeric destination for moderation notices, or `0`; setter must be its admin |
| `xp` | Enable activity XP (at most one point per minute per member) |

Lock names: `links media photo sticker animation video audio voice document contact
location venue poll forward video_note dice game text mention bot story paid_media
live_photo`. `media` combines uploaded media categories; other locks inspect the relevant
Telegram message fields. Links include URL entities, hidden text links and common plain
URL/domain patterns. This is rule-based detection, not a guarantee against every obfuscation.

## Notes, templates and automatic replies

```text
/save faq Our support hours are 09:00–17:00.
/get faq
/custom hours faq
/hours
/notes
/forget faq
/uncustom hours
```

Reply to a photo, sticker, animation, video, audio, voice note, document, video note or
other copyable Telegram attachment using `/save NAME`. File IDs are reused for normal
media; other copyable messages use their original chat/message reference. Protected or
uncopyable content can fail. Media groups are stored as individual messages, not albums.
Reply-based text/captions preserve original entities unless variables require rendering.
Inline HTML can be typed directly in text notes/drafts. Do not mix entity-offset formatting
with templates: placeholders are rendered as HTML and original offsets are omitted.

Variables: `{first_name}`, `{username}`, `{user_id}`, `{chat_title}`, `{chat_id}`. Profile
values are escaped before HTML insertion. Save notes named `welcome` or `goodbye` for
media greetings; these override the corresponding text settings until forgotten.

Rules have a name and JSON definition:

```text
/rule ads {"type":"domain","match":"spam.example","actions":["delete","warn","reply"],"reply":"Advertising is not allowed."}
/rule greeting {"type":"word","match":"hello","actions":["reply"],"note":"faq","audience":"user","bots":false}
/rule suspicious {"type":"pattern","match":"*claim*free*money*","actions":["delete","mute"]}
/unrule ads
```

Match types: `word` (bounded word), `phrase` (substring), `domain` (exact or subdomain),
`user` (numeric ID or username without/with `@`), `pattern` (case-insensitive whole-text
shell glob, `*` and `?`). Patterns are **not arbitrary regular expressions**. Actions
execute in listed order: `delete`, `warn`, `mute`, `ban`, `kick`, `reply`. Punishments do
not apply to native admins/trusted users, but a matching reply may. `audience` is `all`,
`admin` or `user`. Bots are skipped unless `bots:true`; visibility depends on Telegram.
Rule replies can reference any locally saved note. Filters never execute shell/code.

## Verification

Button challenges work in the group and are bound to the joining user ID. Response,
math and image challenges are answered privately so the user can stay muted in the
group. `private` uses a private button. The public deep link contains only the group ID;
the bot retrieves the challenge for the private message sender, preventing another user
from claiming it. Users can have separate challenges in several groups; the latest
private prompt selects which one their next answer applies to.

`web` delivers a secret, expiring link privately and asks for displayed characters. This
basic challenge is a friction step, not strong bot detection. `turnstile` validates the
Cloudflare response server-side and checks hostname/action. Each challenge is single-use,
has five answer attempts and a persistent timeout. Failed/ignored joins are kicked or
join requests declined. An administrator may use `/verify` while it is still pending.
New restrictions by moderators supersede CAPTCHA and cannot be undone by old completion.

Nexora supports the standard `chat_join_request` approval flow, not the newer dedicated
guard-bot query protocol. If private delivery cannot be made, the update is recorded as
uncertain and the pending request expires. Do not configure the bot as a dedicated guard
bot requiring that protocol. Telegram users must ordinarily initiate private contact.

## Federations

```text
/fedcreate Community network
/fedjoin FED_ID
/fedban FED_ID USER_ID reason
/fedunban FED_ID USER_ID reason
/fedleave FED_ID
```

A native admin explicitly subscribes each group. Federation creation sets its owner;
only that owner can change shared bans from a subscribed chat where they remain an admin.
Existing bans are queued when a group subscribes. Actions run through permission checks,
protect admins, and record per-chat job outcomes. Departing a federation cancels its
queued effect and future checks; it does not automatically lift past bans. Federation
unban only clears bans tracked as issued by that federation, preserving local and other
active federation bans. Out-of-band bans made directly in Telegram cannot always be
attributed; inspect before using mass reversals.

## Publishing (private chat)

| Command | Example / purpose |
|---|---|
| `/channel` | `/channel -1001234567890` selects a destination; switch to use several |
| `/draft`, `/draftedit` | `/draft launch text`, or reply to content; edit replaces draft |
| `/drafts` | List draft names in your selected destination |
| `/preview` | `/preview launch` sends the preview privately |
| `/buttons` | `/buttons launch [[{"text":"Visit","url":"https://example.com"}]]` |
| `/publish` | `/publish launch [silent]` queues immediate posting |
| `/schedule` | `/schedule launch 2026-12-01T09:00:00+00:00 every=1d silent` |
| `/jobs` | Your last 100 publishing jobs in the selected destination |
| `/reschedule` | `/reschedule JOB_ID FUTURE_ISO_TIME` also refreshes saved draft content |
| `/cancel` | `/cancel JOB_ID` cancels a pending job you own |
| `/posts` | Published message IDs owned by you in the selected destination |
| `/postedit` | `/postedit MESSAGE_ID new text`, or reply to replacement media |
| `/article` | `/article NAME {"title":"News","content":[{"tag":"p","children":["Hello"]}]}` |
| `/articles` | List locally managed Telegraph article names/URLs |

Drafts and article accounts are isolated by operator and selected destination. Inline
buttons support URL calls to action, up to ten rows/eight per row. Callback buttons that
execute arbitrary actions are not supported. Copy-based attachment fallbacks may not
support captions/buttons/edits; Telegram determines copyability.

Times accept ISO-8601. Without an offset, the selected destination's timezone is used.
Ambiguous or nonexistent daylight-saving times are rejected: supply an explicit offset.
Recurring jobs use fixed elapsed intervals (e.g. every 86400 seconds), not a calendar
"9am local" rule. Missed recurring runs are skipped to avoid a catch-up burst. Editing a
draft does not silently change pending jobs: `/reschedule` refreshes the snapshot.

Post editing supports text, media captions and Telegram-editable photo/video/animation/
audio/document replacements. Albums, inline query publishing and a visual drag-and-drop
calendar are not included. Preview errors are real errors, not successful publications.

Telegraph content uses native node JSON for headings, paragraphs, links, images and
supported embeds. Reusing an article name edits its managed page. The private command
must fit Telegram message length; combine concise nodes or edit in Telegraph after
publication for larger articles. Nexora does not import a pre-existing user's Telegraph
account or manage articles whose token it does not own. Accounts are generated on first
article creation; tokens are stored locally in the database, never sent to users.

## Private support

`/support` starts an explicit relay session and explains that content goes to staff.
`/close` ends a user's session. Staff use `/inbox`, `/close TICKET_ID`,
`/blockuser USER_ID on|off`. Staff replies must reply to a mapped header/copied message
**inside the configured support group**. Only configured staff IDs can send replies.
Attachments use `copyMessage` so staff/user messages are not forwarded with origin labels.
Ticket headers show the user's numeric ID to staff. Unsupported/protected attachments
are not silently dropped: their update is marked uncertain for operator inspection.

`/subscribe` opts in and `/unsubscribe` opts out of support news. A staff member replies
to content with `/broadcast` to queue it. Consent and blocked status are rechecked at
delivery. Joining a group, starting the bot or opening a ticket does not subscribe anyone.
The staff group is an intentional special surface; do not use it as a public moderated
community group. Edited support messages are not automatically relayed again.

## Global super-admin broadcasts

Configure `SUPER_ADMIN_IDS` with numeric Telegram IDs in the private host environment.
There is no in-chat command to grant this role. `/myid` returns the private sender's ID.
Group admins and support admins do not automatically become super admins. All console
commands require a private conversation; campaigns belong to their creating operator.

| Command | Behavior |
|---|---|
| `/superadmin` | Console help, only for configured super admins |
| `/announce users TEXT` | Preview a service announcement to registered private users |
| `/announce groups TEXT` | Preview for observed groups where Nexora remains an admin |
| `/announce all TEXT` | Both audiences; reply to a media message instead of typing text |
| `/announce_send ID CONFIRM` | Queue exactly that preview, within 15 minutes, once only |
| `/announce_status ID` | Counts of pending/delivered/skipped/failed/uncertain/cancelled jobs |
| `/announce_cancel ID` | Cancel pending deliveries; does not recall sent messages |

Super-admin service notices reach observed private contacts unless they opted out via
`/unsubscribe` or were blocked by support staff. `/subscribe` re-enables delivery. `/start`
shows the service-announcement notice. This differs from support-team `/broadcast`, which
still requires explicit subscription; do not use the service-notice route for unsolicited
marketing. Private contact must originate with the user. The bot cannot enumerate every
historical user, nor DM all members of groups it administers.

Recipients are snapshotted at preview, then operator authorization, user opt-out and bot
group-admin status are rechecked at delivery. The staff support group is excluded from
the group audience. Jobs are persistently queued at four-second intervals, honor Telegram
rate-limit delays and do not automatically retry uncertain sends. Removing an operator
from the environment and restarting stops that operator's remaining deliveries. Campaign
content, recipient IDs and delivery records persist in the database; include them in
your retention/erasure policy. `/announce_status` is the delivery report; `queued` on the
campaign means confirmation was consumed, while individual counters show completion.
