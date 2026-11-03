# Triage policy

Order: jm's fixed rules → this policy → the owner's profile (`jm profile` → `profile.md`) → your judgment. Unsure → `keep` (or `newsletters`), never `spam`.

## Fixed rules — jm enforces them, a decision cannot override

- **Protected mail is never queued:** whatever `config.json → protected` lists — domains (with subdomains; `corp*.example` is a glob), exact addresses or globs, recipient local parts (`contact`, `billing-*`), subject words. Empty lists protect nothing.
- **Younger than 30 minutes:** waits for the next window.
- **VIP sender** (`config.json → vip`): only `keep` or `flag`.
- **Spam for someone the owner has written to** (found in Sent To/Cc) becomes `newsletters`.
- No delete, no removing a flag the owner set.
- **Inbox Zero:** `jm archive` moves inbox mail that is read, has no flag, is not from a VIP, is not protected and is older than 7 days into Archive (Gmail: All Mail). A flag means «keep it in the inbox».

## Actions

| Box | Action | Effect |
|---|---|---|
| inbox | `keep` | stays, unchanged |
| inbox | `flag` | stays, gets ⚑ (Gmail: star) — «needs the owner's action» |
| inbox | `newsletters` | → «Рассылки» |
| inbox | `notifications` | → «Уведомления» |
| inbox | `spam` | → the provider's Spam (teaches its filter; deleted by the provider after 30 days) |
| spam | `keep` | stays in Spam |
| spam | `inbox` | back to the inbox — the provider learns «not spam» |

Modifiers: `+seen` (mark read — only with newsletters, notifications, spam), `+flag`.

## What goes where

- **flag** — needs the owner's action. The «Important» list below.
- **keep** — a real person writing personally with nothing to do now; anything you are not sure about.
- **notifications** — services talking about the owner's own accounts with no action needed: receipts and invoices of running subscriptions, payment confirmations, delivery tracking without a step to take, login codes older than 30 minutes, GitHub / LinkedIn / calendar notices, account updates, «your statement is ready».
- **newsletters** — news, digests, product updates, promotions, webinars, «we miss you», community mail.
- **spam** — only obvious junk from a sender the owner never wrote to: phishing, scams, adult, crypto giveaways, cold SEO or marketing pitches to a personal address, mail in a language and topic with no link to the owner. Doubt → `newsletters`.
- **spam → inbox** — a legitimate letter that matters: a real person, a bank or a state body, an order or a delivery, a reply to the owner's outreach.

## Important — flag it and give it a line in the digest

A letter is important when the owner must act on it, or when it touches what the owner's profile names as important now. Without a profile:
- lawyers, courts, police, tax and social-insurance offices, immigration and other state bodies;
- the owner's home: landlord, building administration, utilities;
- clients and payments, invoices to pay, failed payments;
- banks and payment services when an action is needed: a block, a document or KYC request, a failed or suspicious transaction;
- replies to the owner's external steps (outreach, applications, requests);
- a verification link or code that a sign-up the owner started is waiting for;
- deliveries that need a step (customs, pick-up, a failed delivery);
- security alerts about a login or a change the owner may not have made.

For each important letter propose one action: a reply draft (`jm draft`, shown, not sent), a task, or a change of the day's focus.

## Accounts

The account's `role` (from `jm profile`) sets the bias:
- a sensitive inbox (banks, state bodies; usually `digest_senders: true`) — bias to `keep`/`flag`; `newsletters` only for clear marketing from a bank or a shop. The digest names the senders of everything moved there.
- a sign-up inbox (services, tools) — mostly newsletters and notifications; flag only billing problems, security alerts, verifications still awaited and replies from people.
- a personal or work inbox — triage as above.
- **iCloud** — much mail comes through Hide My Email addresses (`hme`). Triage as usual; replies to those threads only from Mail. iCloud has no IMAP MOVE: jm copies, checks the copy, then removes only those originals — slower, same result.
- **Proton** — read through Bridge; often nearly everything is protected (`config.json → protected`) and never queued.
- LinkedIn notifications → `notifications`; a notice that a person wrote to the owner → `keep` (it may be a reply to outreach).

## Fixed sender rules

`config.json → rules` gives `hint` for known senders (e.g. `*@linkedin.com` → notifications). Add a rule when the owner corrects the same sender twice; tell the owner in one line what you added.
