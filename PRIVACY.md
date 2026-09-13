# Privacy and data protection

Written for the person at a fund who has to answer their counsel's questions.

## The short version

This software runs entirely on your machine. It sends nothing to us — there is no
telemetry, no analytics, no licence server, no phone-home of any kind. **You are the
data controller for everything it processes, and we are not a processor**, because
we never receive your data.

## What it collects, and from where

| Source | Data | Basis |
|---|---|---|
| Hacker News, GitHub, Substack, Reddit | Public posts, authors, repository metadata | Published by the author |
| LinkedIn | Public profile and article text | Published by the author |
| WhatsApp | Messages from group exports **you** supply | Your own conversations |
| Inbound | Emails and form submissions **sent to you** | Sent to you directly |

All of it is personal data once tied to an identifiable person, including public
posts. Being public affects the expectation of privacy, not whether the regulation
applies.

## Lawful basis

For B2B investment research, **legitimate interest** (GDPR Art. 6(1)(f)) is the
usual basis. It is not automatic, and it obliges you to:

- collect only what you actually use for scoring — the software stores extracted
  fields and source URLs rather than whole page dumps wherever a record suffices
- set a retention period and enforce it — every record carries `retention_until`,
  and the deletion job runs when the app starts and before every collect, score
  and report run, so the period is enforced rather than intended
- be able to erase an individual on request — one command removes a person from
  every table, including their entity profile and every piece of evidence drawn
  from them
- keep a record of what you hold and why — the database is yours and is inspectable

Run a legitimate-interest assessment before deploying. This software gives you the
mechanisms; it cannot make the assessment for you.

## What leaves your machine

Only inference requests, and only when you configure an API key.

Free model providers generally train on what they receive. The software therefore
requires every caller to classify what it sends and **refuses private text
outright**:

- **Sent:** text that was already published by someone else
- **Sent, redacted:** a fragment extracted from private material, with names, phone
  numbers and surrounding conversation removed
- **Never sent:** raw WhatsApp messages, your thesis prose, assembled reports

WhatsApp and inbound are embedded locally regardless of which keys are set. For a
fund that wants nothing at all to leave, run only local models and accept the speed.

## Special care

- **WhatsApp group members did not consent** to their messages being analysed. You
  are a member of those groups; they are not participants in your research. Keep
  what you extract minimal and treat the archive as confidential.
- **LinkedIn** collection is read-only, capped, and stops on the first challenge
  page. It remains subject to LinkedIn's terms, which are your responsibility.
- **Paywalled content** is never accessed. Public archives only.

## Deletion

A person asking to be erased is a 30-day statutory deadline, so this is a command
and a button rather than something you write code for.

```bash
vc-alpha forget "person name"          # shows exactly what would go
vc-alpha forget "person name" --yes    # erases it
vc-alpha purge                         # delete everything past its retention date
```

The same thing is in the app, under **Setup → Privacy and retention**, which also
shows how many records expire this week. Claude and Codex can do it over MCP with
the `forget_person` tool, which requires an explicit confirmation.

**What erasure covers.** Their candidates, their WhatsApp messages, their activity
history, their entity profile, and every piece of evidence drawn from their posts —
including quotes attributed to them inside someone else's dossier. An earlier
version cleared the first three and left the profile, which meant a fund could
report an erasure complete while the person's name, handle and score were still in
the database. If you ran a version before this one, re-run `vc-alpha forget` for
anybody you have previously erased.

**What it does not cover.** Anything already written out to your Google Sheet, and
anything a provider retained from an inference request. The sheet is yours to edit;
the provider's retention is governed by their terms, which is the reason the
software refuses to send private text at all.
