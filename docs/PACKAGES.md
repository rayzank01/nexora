# Packages, refunds and operator advertising

This guide supersedes the earlier single-group billing foundation in EXPANSION.md.
The implementation is tested locally; no live payments or advertising have been sent.

## Packages

Both purchases cost **154 Telegram Stars**, as approved by the owner. Dollar amounts
are approximate references; checkout uses Stars only.

| Package | Price target | Coverage | Term | Active recurring messages per group |
|---|---|---|---|---|
| Free | Free | Each group | Ongoing | 1 |
| Pro | 154 Stars total | Six group slots | Three calendar months, one-time purchase | 10 |
| Ultra | 154 Stars | One group | 30 days, automatically renewing | 50 |

Pro expires three calendar months after the payment date in UTC; month-end dates clamp
to the last day of the target month. Telegram's recurring invoice is used only for Ultra.
Pro is not a recurring 90-day invoice. Unused Pro slots share the original expiry date;
assigning a slot later does not restart the term. Slots cannot be transferred after assignment.

| Capability | Free | Pro | Ultra |
|---|---|---|---|
| Essential moderation, CAPTCHA, warnings, appeals, privacy | Included | Included | Included |
| New filter rules | 10 | 100 | 500 |
| Automatic reply rules | 5 | 50 | 250 |
| Saved notes | 20 | 100 | 500 |
| Active one-time scheduled posts | 5 | 50 | 250 |
| Active events | 2 | 20 | 100 |
| Analytics history available | Up to 7 days | Up to 90 days | Up to 365 days |
| Media album publishing | — | Included | Included |
| Automatic raid detection | Manual lockdown only | Included | Included |
| Support assignment/priority/internal notes | Basic relay only | Included | Included |
| Topic overrides, templates and bulk settings | — | — | Included |
| Name-similarity alerts | — | — | Included |
| Operator advertising campaigns | Eligible | Excluded | Excluded |

Calendar scheduling retains permission checks and group-wide quotas across all admins.
The observed-data retention setting may be shorter than the plan's analytics allowance;
upgrading cannot recover already deleted history. Existing notes, rules and safety
settings are preserved on downgrade; quotas restrict additions rather than destroying
configuration. Excess scheduled publishing is paused at delivery before sending. Inspect
`/jobs`, cancel unneeded jobs or upgrade and deliberately `/reschedule` the retained job.
AI is separately configured and is not an unlimited included service. Proposed future
features (media classification, named role presets and advanced scheduling windows) are
not advertised as implemented plan benefits.

## Member/admin payment controls

- `/plans`: show package differences, ad policy and refund policy.
- `/plan GROUP_ID`: current group plan and interactive purchase choices.
- `/buypro GROUP_ID,OTHER_GROUP_ID`: choose one to six groups, review terms, confirm invoice.
- `/buyultra GROUP_ID`: review the one-group monthly subscription and confirm invoice.
- `/subscriptions`: own purchases and cancellation/refund confirmation.
- `/assignplan PACKAGE_ID GROUP_ID`: assign an unused Pro slot while the package is active.
- `/paysupport`: private payment support.

Only the payer can cancel/refund their purchase or assign its unused slots. Each selected
group requires current native admin access at purchase/pre-checkout and slot assignment.
Payment never grants admin rights. Group migration updates bundle bindings.

## Seven-day refund policy

A confirmed cancellation refunds payments made within the previous seven days in full,
in Telegram Stars. Each payment, including an Ultra renewal, has its own seven-day window.
A Pro refund removes paid entitlement for the entire six-slot bundle; there are no
per-slot partial refunds. Ultra cancellation first stops future renewal; eligible
payments are then refunded. Refunded entitlement ends, while any separate valid paid
entitlement still applies. After seven days, cancellation does not refund that payment;
existing access continues to its paid expiry. Pro has no automatic renewal to stop.

Refund attempts are recorded before the remote call. Ambiguous results require operator
reconciliation; retries cannot silently issue a second refund. Restored databases freeze
financial operations until records are reconciled. The super-admin manual refund command
remains available for individually reviewed payment-support cases.

## Owner backend and group links

Privately send `/superadmin` from an ID configured in `SUPER_ADMIN_IDS`.
The Group list button or `/operator_groups` shows ten observed groups per page, with
current plan, bot-admin status and an Open group button when Telegram supplies a public
username or existing invitation link. Previous/Next buttons paginate the list.

This is an observed-group inventory, not access to Telegram's full directory or a full
member roster. A link does not bypass membership approval or bans. For a private group
without an available invitation, the panel displays that no access link is available;
it does not create invitations or grant itself access. Failed/inaccessible groups are
shown as unavailable. Operator access is rechecked when a button is clicked.

## Advertising in free groups

1. Open `/superadmin` → Advertise in free groups.
2. Send `/advertise YOUR AD TEXT`, or reply `/advertise` to supported media.
3. Inspect the private content preview and eligible destination count.
4. Send `/announce_send CAMPAIGN_ID CONFIRM` within 15 minutes.
5. Track `/announce_status CAMPAIGN_ID`; `/announce_cancel CAMPAIGN_ID` cancels pending deliveries.

The separate ad audience contains only observed Free groups where the bot is currently
an administrator. Operator and registered community support inboxes are excluded.
Plan status and bot rights are checked again before every delivery: a newly upgraded
group is skipped. No private users are targeted by `/advertise`. Deliveries are paced,
durable and cancellable; uncertain sends are not blindly retried. Already sent ads cannot
be recalled by cancelling the campaign. Setup and plan menus disclose free-group advertising.
The existing general `/announce` service-announcement controls remain separate.

## Activation

Set privately on the host:

- `NEXORA_PRO_STARS=154`: complete three-month, six-group bundle.
- `NEXORA_ULTRA_STARS=154`: one group for each 30-day subscription period.
- `NEXORA_BILLING_TERMS`: the published product/refund terms.
- `SUPPORT_CHAT_ID` and `SUPPORT_ADMIN_IDS`: staffed payment-support destination.
- `NEXORA_BILLING_ENABLED=1`: enable configured checkout.
- `NEXORA_PLAN_LIMITS=1`: enforce plan capabilities and quotas.

Prices default to 154 Stars. Billing and plan limits remain disabled until private
host configuration and published terms are ready. Do not enable a paywall without an available configured checkout. No live
purchase, refund, campaign or deployment was performed during implementation.

## Verification

174 local tests passed, including 19 package/operator tests for six-group isolation,
calendar-month expiry, slot ownership, Ultra recurrence, receipt replay, cancellation
and refund windows, refund ownership/recovery guard, quotas, paused scheduled delivery,
group migration, operator access revocation, clickable links, staff-inbox exclusions
and upgrades between advertising preview and delivery. Telegram responses were mocked.
