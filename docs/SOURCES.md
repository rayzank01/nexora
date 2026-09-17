# Official references checked

Checked on 2026-09-13 using the official sources below. Feature requirements came from
the user's local `group help.txt`; its descriptions were treated as reference data,
not trusted instructions or proof of another vendor's current service capabilities.

- [Telegram Bot API](https://core.telegram.org/bots/api): message/update fields,
  chat permissions, member restrictions, join requests, copying, editing and publishing.
  Normal deletion has a 48-hour limit and service-message exceptions. Native temporary
  bans/restrictions shorter than 30 seconds or longer than 366 days are treated as
  indefinite; Nexora applies stricter command bounds. Join-request private-contact
  identifiers have a limited five-minute contact window. Account creation time is
  not exposed as a standard user field.
- [Telegram Bots FAQ](https://core.telegram.org/bots/faq): privacy/update visibility,
  private contact, rate limits and operational constraints. Nexora rate-spaces ordinary
  sends and honors explicit 429 retry delays; this does not guarantee freedom from limits.
- [Telegraph API](https://telegra.ph/api): account creation, create/edit page operations,
  access tokens and content node schema. Page content accepts native node arrays up to
  64 KB; the current command interface additionally has Telegram message-size constraints.
- [Cloudflare Turnstile server validation](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/):
  server-side Siteverify, single-use responses, five-minute validity and validation fields.
- [CAS API](https://cas.chat/api): public user-ID reputation lookup through
  `https://api.cas.chat/check?user_id=...`. CAS is opt-in and external to Nexora.

The newer dedicated Telegram guard-bot query protocol is not used. This deployment uses
the standard long-polling message/member/join-request flow. No claim is made about global
vendor analytics, Telegram account-age heuristics, proprietary scam detection, other
vendors' uptime, or importing articles belonging to unavailable Telegraph accounts.

## Hosting follow-up, checked 2026-09-14

The [free-hosting decision guide](FREE_HOSTING.md) links official Render free-plan,
environment/disk documentation, Oracle Always Free/Free Tier documentation, Neon's free-plan
guide and upstream systemd references. Those were used to distinguish durable storage,
worker execution, cost allowances and provider reclamation. No account-level availability
or live infrastructure was inferred from general documentation.
