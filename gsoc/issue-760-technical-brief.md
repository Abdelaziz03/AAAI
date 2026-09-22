# Technical brief — extraction-framework #760: DurationParser fails for non-Latin duration words

Issue: https://github.com/dbpedia/extraction-framework/issues/760
Verified open & unassigned: 2026-09-22 (it's a live public tracker — recheck before you start).

## Root cause (confirmed from source, not guessed)

File: `core/src/main/scala/org/dbpedia/extraction/dataparser/DurationParser.scala`, around line 129:

```scala
val unit = timeUnits.get(m.subgroups(1).replaceAll("""[^\'\"a-zA-Z]""", ""))
```

After the duration regex captures the "unit" text following a number (e.g. "ώρες", "ساعات"), this line strips every character that isn't `a-zA-Z`, `'`, or `"` before looking the result up in `timeUnits` (the per-language map from `DurationParserConfig`). Any duration word written in a non-Latin script — Greek, Arabic, Cyrillic, etc. — is reduced to an empty string by this line and can never match `timeUnits`, regardless of what's configured. This matches the issue reporter's own diagnosis exactly (Greek "ώρες" fails despite being configured).

`timeUnits` itself is resolved per-language a few lines above:

```scala
private val timeUnits = DurationParserConfig.timesMap.getOrElse(language, DurationParserConfig.timesMap("en"))
```

So the fix belongs in the character-stripping regex, not in the map-lookup mechanism.

## What to check before touching the fix

- Find `DurationParserConfig.scala` (under `core/src/main/scala/org/dbpedia/extraction/config/` — I could not pull a stable raw URL for it during research; grep for `timesMap` once you have the repo cloned) and confirm whether `"ar"` already has an entry. Treat it as absent until you've actually checked — I have not verified this directly.
- Look at `DurationParserTest.scala` for the existing test harness shape. The issue itself suggests mirroring it with a Greek case — that's your template for an Arabic case too.
- Grep the rest of `DurationParser.scala`, and any sibling `*Parser.scala` files in the same package, for the same `[^\'\"a-zA-Z]` pattern. If it's copy-pasted elsewhere for the same reason, fixing only this one spot leaves the same bug live in a sibling parser — worth knowing before you scope the PR.

## Shape of a fix (design notes, not code — this part is yours)

- Replace the ASCII-only character class with a Unicode-aware one — e.g. `\p{L}` (any Unicode letter) instead of `a-zA-Z` — so Arabic, Greek, Cyrillic, etc. letters survive the strip. Keep `'`/`"` in the allowed set unless you determine they're not needed.
- Watch for regressions: this line likely exists to strip trailing punctuation/brackets caught by the outer regex (e.g. "min)" → "min"). Confirm `\p{L}` still strips digits, punctuation, and brackets correctly, and write a test proving it — don't just eyeball it.
- Arabic adds a wrinkle the Greek example doesn't fully exercise: duration nouns inflect for singular/dual/plural (e.g. ساعة "hour" / ساعتان "two hours" / ساعات "hours"; دقيقة/دقيقتان/دقائق for minute; يوم/يومان/أيام for day). Deciding whether to register all three forms per unit in `timesMap`, or normalize input before lookup, is a linguistic call — make it yourself and document why in the PR description.
- Add test cases to `DurationParserTest.scala`: at minimum the issue's own Greek example, one Arabic case per unit you add, and one regression case proving the punctuation-stripping behavior still works after the change.

## What I deliberately did not do

I did not write the patch, did not add Arabic map entries, and did not open a PR. That's the part that has to be recognizably your own engineering and linguistic judgment — it's the actual skill a mentor is evaluating, and DBpedia (like most GSoC orgs) treats AI-authored contributions as a red flag. This brief exists to skip the "where's the bug" archaeology so you can go straight to designing and testing the fix.
