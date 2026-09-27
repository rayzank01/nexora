# Public bot expansion — setup and completion audit

Verified locally on 27 September 2026. This release preserves the original moderation,
publishing, analytics, support and super-admin announcement features and adds the
following workflows. It is a source release, not a running Telegram service.

## Public onboarding and isolation

In BotFather, allow the bot to join groups. Anyone can add it to a group and grant the
required Telegram admin rights. Send `/panel` inside that group, or `/panel GROUP_ID`
privately. There is no bot-owner allowlist for ordinary group administrators. Anonymous
admin messages are ignored; use your visible identity. Group configuration requires
current native Telegram admin membership. Delegated Nexora roles can perform their
approved moderation tasks but cannot become native admins or control other groups.

`/start` offers Add to group, group selection, privacy and language buttons. The private
`/dashboard GROUP_ID` link opens analytics and links to the multi-group control panel.
Every destination is checked independently on every read/change. Tokens expire and
callbacks are bound to the acting user, chat and destination. Payment never grants
admin access. Only environment-configured `SUPER_ADMIN_IDS` control global announcements.

## All 14 additions: behavior and evidence

Test names below are in `tests/test_expansion.py`, `tests/test_public_bot.py` and
`tests/test_final_review.py`. The full suite has 155 passing tests including the original
88 regression checks. These use synthetic users and mocked Telegram, not live customers.

| Addition | Runnable workflow | Meaningful verification |
|---|---|---|
| 1. Interactive setup | `/panel` or `/setup` → Setup wizard; choose a setting, type a value if needed, review and confirm; Back/Cancel navigation | `test_callback_cannot_cross_user_or_chat`, `test_callback_expired_single_use_revocation`, `test_wizard_plain_text_confirmation_and_stale_setting`, `test_private_prompts_remain_group_scoped` |
| 2. Anti-raid | Panel → Moderation & raid; configure distinct join/spammer thresholds and window; automatic/manual temporary lockdown | `test_raid_distinct_users_and_expiry_keeps_new_settings`, `test_old_raid_expiry_cannot_remove_new_lockdown` |
| 3. Appeals | Member privately sends `/appeal GROUP_ID`; native staff privately use `/appeals GROUP_ID`, review reason, approve/reject | `test_appeal_does_not_override_external_action`, `test_appeal_success_is_single_decision`, `test_preexisting_restriction_not_appealable_automatically`, `test_appeal_review_only_private_and_authorized` |
| 4. Rule testing | Panel → Topics & rules → Test sample; newly entered filters require a sample before Enable confirmation; `/test` tests a supplied/replied sample | `test_dryrun_matches_without_writes_or_actions`, `test_filter_wizard_tests_before_enabling` |
| 5. Multi-group/templates | Private `/panel` selector; web `/console`; save/apply safe policy templates; bulk template preview lists destinations before confirmation | `test_template_excludes_content_roles_and_checks_destination`, all three `test_bulk_template_*`, `test_modified_template_requires_new_preview`; browser changed one group and verified the other remained unchanged |
| 6. Impersonation review | Raid menu → name alerts, threshold 0.75–1.0, numeric member exceptions | `test_name_alert_is_review_only_and_exceptions`; normalization/similarity produces notices, never automatic punishment |
| 7. Topic overrides | `/panel` inside a forum topic; topic rules/locks/filters/replies and Restore inheritance | `test_topic_filters_isolated_and_replies_in_topic`, `test_topic_settings_inherit`, `test_topic_flood_counters_do_not_bleed` |
| 8. Staff support | Operator `/ticket ID`; community `/cticket GROUP_ID ID`; assignment, four priorities, internal notes, close, first response timing and unresolved reminders | `test_ticket_notes_never_relay_and_assignment_checked`, `test_resolved_ticket_suppresses_reminder`, independent routing/revocation/nonstaff/notes/command tests in PublicBotTests |
| 9. Publishing/calendar | Private `/channel GROUP_ID` then draft/import; `/album NAME` replying to an observed photo/video album; panel/web recurrence; visual calendar move/cancel | DST gap/fold tests, revoked recurring permissions, album ordering/namespace/API IDs, stale calendar job test; browser moved a post to another date/time |
| 10. Backups/recovery | Set `NEXORA_BACKUP_DIR`; periodic checked SQLite backups with bounded retention; private operator `/backups`; offline restore command below | `test_backup_retention_and_integrity`, `test_restore_lock_digest_and_uncertain_deliveries` |
| 11. Privacy/retention | Private `/privacy` export, deletion and AI capture opt-out buttons; group panel/web retention days | `test_privacy_export_deletion_isolation`, `test_community_notes_not_in_personal_export_and_delete_isolation` |
| 12. English/Malayalam | Group wizard language or `/set language "ml"`; personal `/language ml`; web language selector; localized verification and API errors | `test_private_language_and_localized_menus`, two HTTP language tests, language-switch defaults test; browser checked translated menu options, weekday headings and accessible form labels |
| 13. Events/polls | Panel → Events; create/edit/cancel, publish RSVP card, reminders, polls and quizzes; equivalent console forms | `test_event_rsvp_membership_and_cancel`, `test_event_edit_invalidates_old_reminder`, `test_event_edit_after_preview_is_preserved` |
| 14. Optional AI | Configure Ollama explicitly, enable per group; approved knowledge + `/faq`; panel observed-message summary and advisory review | AI two-opt-in, external consent, cross-group context, no executable output, personal opt-out and support exclusion tests |

## Behavior and operational limits

**Raid protection:** Nexora deletes non-exempt messages during the temporary lockdown.
It does not replace Telegram's global chat permissions. Existing CAPTCHA/join policies
continue separately; the bot must be online with deletion rights. Ending or expiring a
lockdown cannot overwrite a newer group policy or newer lockdown revision.

**Appeals:** automatic reversal is limited to eligible actions recorded as issued by
this bot, with a matching current restriction fingerprint. Pre-existing restrictions,
federation bans, later moderator changes and uncertain results require human handling.
Approval is one decision; network ambiguity is not silently retried.

**Names/topics:** name alerts use profiles on messages the bot receives; Telegram does
not supply a complete name-change history or member roster. Similarity is not proof of
impersonation. Topic rules overlay group rules by name; deleting an override restores the
group version. Replies preserve the originating topic, and flood counters are topic-scoped.

**Community support:** Panel → Community support → Configure private staff inbox asks
for `INBOX_ID | STAFF_ID,STAFF_ID`. Use a separate private group with only the bot and
those staff; they must be native community admins. The inbox cannot be shared across
communities or with operator support. Members explicitly start `/csupport GROUP_ID`
privately; `/support` selects operator support and `/close` closes the active route.
Rights and expected inbox membership are checked before routing. Telegram cannot make a
membership check and message delivery atomic: trusted staff must keep the inbox private.
Internal notes remain staff-only. Ticket replies must reply to a mapped header/copy.

**Calendar/albums:** wall-clock recurrence uses the group's timezone when created. A
spring-forward missing time is skipped; a repeated autumn hour uses its first occurrence
once. Following downtime, at most one overdue occurrence is processed before advancing
to a future occurrence, rather than replaying all missed posts. Moving a recurring post
in the calendar converts it to a one-time post. Changing the group's timezone does not
rewrite existing schedules. Original fixed-interval schedules remain supported. Albums
contain 2–10 observed photos/videos sorted by Telegram message ID; save only after all
items arrive. Telegram albums do not support attached inline keyboards. Published album
items are recorded individually for editing; no live Telegram album was sent in QA.

**Events:** reminders are durable and revision-bound; edits/cancellation invalidate old
reminders. Reminders go to the group, not unsolicited private member messages. RSVP
buttons expire after at most seven days; publish a fresh card for a more distant event.
A crash or ambiguous remote delivery becomes uncertain rather than duplicate delivery.

**Privacy:** exports contain only the requester’s stored personal data, own drafts and
support metadata without internal staff notes. Activity export is bounded to 1,000
recent records. Deletion clears local activity/profile/points, own captured AI messages,
drafts, RSVPs, own support mappings and pending user-owned outbound work. Active safety
records, moderation configuration/audit evidence and payment ledgers are retained.
Telegram copies, exported files and separate backups are not remotely erased. Group
retention removes old observed activity, inactive profiles/points and closed tickets;
active safety records and open tickets are separate. Retention is not a promise of
retroactive erasure from all systems.

**Languages:** `nexora/locales.json` is the maintained English/Malayalam catalog;
`i18n.py` also handles dynamic message patterns. Commands, technical identifiers,
user-authored content, exported JSON and remote-service diagnostic details keep their
original representation. Translations are supplied with the project; independent native
speaker review remains advisable before a large public launch.

## Backup and restore

Set `NEXORA_BACKUP_DIR` to a private persistent directory outside source. Defaults:
`NEXORA_BACKUP_SECONDS=86400`, `NEXORA_BACKUP_KEEP=7` (count, maximum 90). Each backup uses
SQLite's online backup API and an integrity/schema check. `/backups` reports the last
attempt. Maintain an independent off-host copy and suitable OS access controls.

Stop the worker, inspect the backup and obtain its SHA-256. Then run:

```powershell
python -m nexora.maintenance --db data/nexora.sqlite3 restore PATH_TO_BACKUP --sha256 EXACT_SHA256 --confirm-restore
```

The same instance lock rejects a running worker. A checked rollback backup is created
before restoring. Restored pending/running updates and jobs become uncertain, and access
sessions/buttons are invalidated. Inspect these jobs and remote Telegram state before
recreating intended work. A successful database restore does not reverse Telegram actions.
Billing is frozen after restore: reconciliation of local charges with Telegram records
must precede any operator removal of the recovery block. There is intentionally no
chat button to bypass this review. Backups and rollback files must never enter GitHub.

## Optional AI setup

Install Ollama and download an appropriate model separately. Set `NEXORA_AI_ENABLED=1`,
`NEXORA_AI_MODEL` to that installed model, and keep `NEXORA_AI_URL` at the local service
unless intentionally configuring a compatible HTTPS provider. Then enable AI in the
group panel and add approved FAQ sources. No model is bundled and no service is purchased.
Running a model may need substantially more resources than the approved small bot host.

External processing requires both `NEXORA_AI_ALLOW_EXTERNAL=1` and that group's separate
consent. Capture is another explicit group choice with a posted notice; individual
members can opt out. Summaries use at most 100 observed messages from the previous 24
hours, never fabricated Telegram history or private support messages. Retrieval is
limited to that group's approved knowledge. Inputs are treated as untrusted data, the
model has no moderation tools, and outputs are labeled advisory. Human review is still
required: these boundaries do not guarantee factual accuracy or eliminate prompt injection.

## Earlier disabled billing foundation

**Superseded by [Packages](PACKAGES.md):** Pro now covers six group slots for three
calendar months; Ultra covers one group for 30 days; cancellation has a seven-day
refund window. Actual Stars amounts and live activation remain pending.


All features remain available: no live price, quota or paywall has been chosen.
`NEXORA_BILLING_ENABLED=0`, `NEXORA_PRO_STARS=0` and blank terms are intentional defaults.
The foundation implements group-bound 30-day Telegram Stars subscriptions, checked
pre-checkout, receipt deduplication, renewal, payer cancellation and operator refunds.
`/plan GROUP_ID` explains current status; `/upgrade GROUP_ID` offers an invoice only
when explicitly configured. `/subscriptions`, `/terms`, `/paysupport` and private
super-admin `/refund CHARGE_ID` provide lifecycle/support entry points.

To launch commercially later, decide the actual price, precise paid benefits/limits,
terms and support arrangements, implement/approve their enforcement, then configure
billing. Setting a price alone does not activate feature limits. Receipts confer group
entitlement only, never admin membership; downgrade preserves data and moderation.
Restore or ambiguous financial results require reconciliation. No customer was charged.

Implementation references: [Telegram Bot API](https://core.telegram.org/bots/api),
[Telegram Stars payments](https://core.telegram.org/bots/payments-stars),
[Ollama chat API](https://docs.ollama.com/api/chat),
[Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html),
[SQLite online backup](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).
