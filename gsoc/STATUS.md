# GSoC 2027 — Status Log

Purpose: keep an honest, dated record of what has actually been done versus what's still pending, so [GSOC_2027_ACTION_PLAN.md](../GSOC_2027_ACTION_PLAN.md) stays a plan and doesn't get mistaken for a report of completed work.

## Decided

- **Primary org: DBpedia. Backup: ML4SCI.** Locked in 2026-09-22, per Recommendation 1 in the action plan. No new information since the plan was written has changed this.

## Verified 2026-09-22

Re-checked live on GitHub (not just trusted from the earlier research pass — these are public issue pages, checked directly):

| Issue | Status | Assignee | Notes |
|---|---|---|---|
| [#760](https://github.com/dbpedia/extraction-framework/issues/760) — non-Latin duration words | Open | None | Best fit — directly touches Arabic-script handling. Brief written: [issue-760-technical-brief.md](./issue-760-technical-brief.md). |
| [#825](https://github.com/dbpedia/extraction-framework/issues/825) — GenderExtractor hardcoded URIs | Open | None | Straightforward refactor, no non-Latin angle. |
| [#819](https://github.com/dbpedia/extraction-framework/issues/819) — default User-Agent | Open | None | Smallest/simplest of the four. |
| [#755](https://github.com/dbpedia/extraction-framework/issues/755) — J.K._Rowling typo | Open | None | Trivial data fix. |

All four are still live and unclaimed as of this check. Re-verify again before you actually start — this is a public tracker anyone can pick up, and this table goes stale the moment someone else comments.

## Ready for you to act on

- **Technical brief for #760** — [issue-760-technical-brief.md](./issue-760-technical-brief.md). Root cause is identified from the actual source (not guessed); the fix design, Arabic word list, tests, and PR are left to you — see the brief for exactly where the line is drawn and why.
- **Draft forum introduction** — [drafts/forum-introduction.md](./drafts/forum-introduction.md). Skeleton only; rewrite in your own words before posting, from your own account.
- **Draft first-contact message to mentor @tsoru** — [drafts/mentor-message-tsoru.md](./drafts/mentor-message-tsoru.md). Send only once you have a real PR to point to.

## Blocked on you (not something an assistant should do)

- [ ] France work-eligibility confirmation for the GSoC program duration.
- [ ] GE HealthCare contract review (outside-work/moonlighting, stipend-acceptance, IP-assignment clauses). Happy to help read specific clauses if you paste the relevant text — I don't have the document.
- [ ] Public GitHub profile polish. This session only has write access to this `AAAI` repo; if you want help drafting a profile README for `Abdelaziz03/Abdelaziz03` or working in a fork of `dbpedia/extraction-framework`, grant this session access to that repo and say so explicitly.
- [ ] Everything that requires acting as you on an external platform: creating forum/Slack accounts, posting introductions, opening PRs against `dbpedia/extraction-framework`, emailing mentors. I can draft the words and the technical analysis; you have to be the one who writes the code, tests it, and hits submit — both because GSoC orgs treat AI-authored contributions as grounds for rejection, and because the mentor relationship the whole process runs on has to actually be with you.

## Next concrete action

1. Read [issue-760-technical-brief.md](./issue-760-technical-brief.md).
2. Fork `dbpedia/extraction-framework`, reproduce the bug locally using the Greek example from the issue.
3. Design and implement the fix yourself, add Arabic + regression test cases, open the PR from your own account.
4. Personalize and post the forum introduction — that's what actually starts the mentor relationship.
