# Build log

Running record of what has actually been built, against the phases in
`docs/health-dashboard-plan.md`. Newest entry first. Append an entry at the end
of each working session.

---

## 24 September 2026 (evening) — feedback that saves, and three layout fixes

- **The brief's "Was this useful?" buttons saved nothing.** They lit up
  through a leftover demo toggle and never called `POST /brief/{id}/feedback`,
  which had existed all along. That rating is the ground-truth signal for
  judging the brief (plan 9.4), so a control pretending to record it was
  worse than none. Now stored, shown back from `/today` on reload, and undone
  on screen if the save fails.
- **The empty brief card** stretched to the readiness card's height: ~450px
  of blank panel on desktop. With no brief it now sizes to its content.
- **The muscle figure used the readiness band's colours** — red worked, amber
  recovering, green ready — so beside an amber score an amber shoulder read
  as a second warning. Time since a session is a fact, not a verdict: it now
  uses one accent hue, strongest where the stimulus is freshest.
- **Tile footers broke mid-phrase** in the four-across row ("Samsung /
  Health" beside "20 nights over 30 / days"). Items stay whole and the second
  drops to its own line when the pair does not fit.

Seen while checking: with the 8h target, today's readiness on the review
data went from 62 to 51 and Sleep trend from 2/7 to 0/7 — the same nights,
now counted against a higher bar.

238 tests passing.

---

## 24 September 2026 (later) — an 8-hour target, and a supplements card that ticks

### Sleep target 7h30 → 8h

The owner's original ask was "nights hitting 8h"; 7h30 was a default that
stuck. `SLEEP_TARGET_MIN` defaults to 480. Sleep debt and the Sleep trend tile
both read this one value, so they move together. **A `.env` copied from the
old example still sets 450 and wins over the default** — this container's did.

The test suite now pins 450 in `conftest.py`, as it already pins the
timezone: the engine tests assert the debt arithmetic against fixtures whose
ordinary night is 450 minutes, not the owner's preference. One test checks
the shipped default.

### Supplements card

Built on the existing checklist API: tap to tick, "All taken", a count and
the 7-day adherence. Ticks are optimistic and undone if the save fails, and
carry the checklist's date so a page left open past midnight files them under
the right day. Three problems surfaced by using it:

- **Workout-day items could never be ticked on the day.** They appeared only
  once a workout was logged, and Hevy syncs at 05:45 UTC, so an evening
  session arrived the next morning — at which point BCAA and beta-alanine
  became "scheduled" and counted as missed. The checklist now returns them
  as `if_training`, tickable, counting only once a workout for the day lands.
- **Adherence read 14% on the first day of ticking**: the six untracked days
  before it counted as everything missed. The window now starts at the first
  logged day, and is None before anything has been logged.
- **The brief was told the whole stack was missed, every morning**, for the
  same reason. `missed_on` is empty before tracking began.

236 tests passing.

---

## 24 September 2026 — a full review: four backend bugs, and a screen that ignored its data

Asked for a review of everything built so far. Every bug below was shown to
fail on the old code before it was fixed. 232 tests passing.

### Backend (`03f28d1`)

- **Overnight wear rate counted check-ins, not nights.** A check-in without a
  `no_watch` tag counted as a worn night, so a watch in a drawer read 100%. It
  now counts distinct sleep dates over seven days, and is None when no sleep
  has ever been recorded.
- **The export dropped 11 of 21 tables**, `workout_sets` among them — every
  set, rep and weight. It was an allow-list that new tables fell out of. Now a
  deny-list over the schema, excluding only `oauth_tokens`, and it keeps nulls.
- **Supplement adherence reported 100% against a true 42.9%.** Every taken log
  counted against the scheduled total, so creatine taken on rest days filled
  in for missed doses. Only scheduled (day, supplement) pairs count now, and
  an empty schedule is None rather than 0%.
- **Re-running the brief paid for a second generation and sent a second
  email.** It now reuses today's brief unless forced and never re-sends one
  already delivered.

### Today screen and check-in form (`5cc3941`)

- **Sleep, resting HR and weight always said "no data".** The live mapping
  was hard-coded to empty series from before any data existed. `/today` now
  carries a week of each (gaps as null), the weight EWMA series, and each
  tile's real source; weight had been labelled "Withings" over Samsung data.
- **Steps and Sleep trend were greyed out as "Coming soon"** over 1,950 days
  of steps. Both built. Sleep trend counts nights at or above the same target
  sleep debt uses, shows typical bedtime (new `typical_bedtime_minutes`,
  median across midnight) and midpoint SD, and draws unmeasured nights as
  gaps rather than misses.
- The RHR line was drawn straight across missing days — an interpolation.
- The status glyph was "!" whatever the band.
- The brief card rendered filler text and offered "Was this useful?" on a
  brief that did not exist; it now renders the brief's real fields, escaped.
- The supplements card showed a made-up stack with three items ticked and
  struck through. Replaced with an empty state until the tick UI exists.
- **The check-in form pre-selected yesterday's overall score** — one tap to
  record a number nobody chose — and copied yesterday's tags and note. Only
  the seven scales carry over now, under a banner saying so.
- **Checking in from abroad could 400.** From Tokyo the phone's date is
  London's tomorrow; the form now takes the date from the server.

### Not done, deliberately

Suggestions rather than fixes, handed to the owner: the import's hot loop
(R1), `GET /metrics/{day}` writing to the database, the Hevy backfill ignoring
`since`, Withings OAuth state held in memory, the empty brief card's size on
desktop, amber shared between readiness and the muscle figure, and whether the
sleep target should be 7h30 (config) or the 8h originally asked for.

---

## 15 September 2026 (later still) — the cap moves to 180, and says how old it is

Two measurements settled a decision that had been argued about twice, and both
measurements had to be fixed first because neither worked.

### The two broken measurements

The span column read **30 days for every candidate rule**, including the
365-day one. A median across all of a rule's days sits inside his dense
stretches where 30 days always sufficed, so it was structurally blind to the
tail where widening actually operates — it could not have discriminated
between the rules whatever the data said. It now reports the span of the days
each rule *adds*, which is where the staleness lives.

The drift check let a year of nineteen nights outvote a year of two hundred
and fifty. It reported a 75-minute spread and concluded the sleep norm drifts;
weighted by sample size the spread is **16 minutes** — 2024's 455 against
2025's 471 — and the norm is stable. A thin sample had been promoted into a
design decision, which is the same failure as quoting a synthetic number as a
measurement, arriving from a different direction.

### What the corrected measurements said

    30-day window only   27.4%
    prefer 30, widen 90  30.8%
    prefer 30, widen 180 36.1%   <- chosen
    prefer 30, widen 365 46.2%

Stopped at 180 rather than 365, despite ten more points being available: six
months stays inside one seasonal half, where a year blends summer and winter
sleep into one median. The extra coverage is not worth a baseline that
averages across both.

The framing that decided it: **on the days a wider cap adds, the alternative is
not a fresher baseline — it is no score at all.** A stale comparison that
admits its age beats silence.

### Which is only true if it does admit its age

So `span_days`, computed since the 14th and displayed nowhere, is now on the
sleep tile: *"25 nights over 151 days"*. Nights first, because fourteen nights
across four months and fourteen across four weeks are different evidence and
the count alone does not distinguish them.

Verified against a deliberately sparse history — 20 nights scattered over five
months — which produces a baseline reaching 151 days back. Under the old
90-day cap that day had no baseline at all; it now has one, and the screen
says exactly how far it reaches.

### Also noticed, not acted on

2023 holds **no sleep data whatsoever**, and 2026 holds 19 nights against
2024's 250. And 2026's median is 396 minutes against 455 and 471 in the two
years before it. At that sample size it is probably noise — but if it is real
it is an hour less sleep a night, which would be the most interesting thing in
the dataset. Worth re-checking once the Air produces a denser sample.

---

## 15 September 2026 (later) — the prediction was a third right

`scripts/verify_readiness.py` walks every day of the imported history and
recomputes the score, because the 14 Sep rework had only ever run against
fixtures and a synthetic export. It found one wrong number of mine, one real
design problem, and corrected a second wrong number I had written down the day
before.

### The baseline prediction was wrong

I claimed the adaptive window would take sleep-baseline availability from 2.8%
of days to **69.9%**. Measured over all 2,041 days: **30.8%**. The 30-day
window alone gives **27.4%**, so the widening bought **+3.4 points**, not
sixty-seven.

*(Corrected later the same day. The first write-up of this entry said the
30-day figure was 19.5% and that reaching past 90 days bought nothing. Both
came from an 87-day synthetic database and were published as measurements of
his history — the same mistake as the 69.9%, made while correcting the 69.9%.
See below.)*

The tell was in the run's own output — the reportable baselines reach back a
**median of 30 days**, meaning most came from the preferred window and the
widening rarely fired at all.

What reaching further would buy, measured against his real history rather than
guessed at:

    30-day window only        559 days   27.4%
    prefer 30, widen to 90    629 days   30.8%   <- current
    prefer 30, widen to 180   736 days   36.1%
    prefer 30, widen to 365   942 days   46.2%

So it keeps paying, and a year-long cap would nearly double the plain 30-day
figure. That is now an **open decision** rather than a settled one, because
coverage is not the only question: the days a wider cap adds are exactly the
ones whose nearest fourteen nights are months old, and a deviation measured
against a stale median is a weaker claim than one measured against a current
one. The script gained two measurements to settle it — the median span each
rule actually produces, and whether his sleep norm drifts from year to year.
If the norm is stable a year-old median is a fair comparator; if it drifts, a
wide window measures the drift rather than last night.

The error was in the model, not the code. I modelled his wear as evenly spaced
clusters; the real pattern is dense streaks separated by long dead periods.
The change is worth keeping, but only just: 27.4% to 30.8% is a smaller
improvement than any figure previously attached to it.

**Three wrong numbers have now been published about this one constant, and all
three came from estimating instead of measuring.** 69.9% came from a model of
his wear pattern. Then 19.5% and "widening past 90 buys nothing" were written
into `CLAUDE.md`, the plan's D13, the module comment and this log as
measurements — while correcting the first one — when they had actually come
from the 87-day synthetic database used to smoke-test the script. The real
numbers are above. `CLAUDE.md` now carries an instruction not to quote a
coverage figure for this that did not come from a run against his database.

The script gained a `compare_windows` pass so this is a measurement next time
rather than an argument: it applies every candidate rule to the same series
and prints what each would give.

### Nearly half the scored days can only go down

752 days score, 1,289 refuse at zero coverage. Of the 752, **352 — 47% — have
no component available except sleep debt and ACWR.** Both are penalties with
no credit; there is no such thing as less than no sleep debt. Those days have
the neutral score as a *ceiling* and can only report neutral-or-worse however
well the morning went.

A further **113 land exactly on neutral and read green**, where what is
actually being said is "nothing adverse is visible" — which is not the same
claim as "this was a good morning" and should not wear the same colour.

So the median score of 56.2 is partly an artefact of which components happened
to be available rather than of how he was doing.

**Fixed the same day, once he asked for it.** The band is capped at amber when
no two-sided component is available. Green now means measured and good; amber
covers "nothing bad visible, but I could not see much". The number is
untouched — capping by adjusting the score would corrupt every trend built on
it — and only the colour and the accompanying sentence change.

Withholding the score on those days was the other candidate and was rejected:
it would blank 352 days, against the standing instruction that the dashboard
stay useful on the mornings he forgets to measure. Red is left alone too, on
the same logic in reverse — a saturated sleep debt is bad news whoever reports
it, and the cap only ever moves a day down.

Four tests cover it, two of which fail against the previous code.

**Measured after the fact:** green fell from 247 days to 114 and amber rose
from 370 to 503, so 133 days changed colour — slightly more than the 113 that
sat exactly on neutral, because one-sided days scoring between 65 and 75 were
green too. Red is unchanged at 135, as intended: the cap only ever moves a day
down.

### And one thing I had got wrong the other way

The synthetic dry run showed 38 of 38 baselines flagged `potentially_biased`,
and I wrote in `comments-to-revisit.md` that a warning firing on every baseline
carries no information. The real history says 425 biased against 204 ok —
67.6%, not 100%. The flag does discriminate. The note is corrected rather than
deleted, because the synthetic inference being wrong is the more useful record.

### What came back clean

No score clamped at either end, so the scale has room at both ends. No day
refused with partial coverage under the 10% floor — every refusal was at zero.
That last one is worth noting for a different reason: **the coverage floor
never actually fires**, so the constant is currently decorative. Harmless now,
but a future change to the weights could silently make it bite.

---

## 15 September 2026 — the device changed, and took the hardest phase with it

A spec change, no code. The overnight sensor becomes a **Fitbit Air**, and the
consequence is larger than swapping one device for another: it removes the
biggest unbuilt piece of the plan.

### Why it matters more than a device swap

§3.3 has said since the plan was written that **Health Connect is an on-device
API with no cloud endpoint**, and the entire Phase 3 companion app existed to
work around that one sentence. An Expo dev build, a config plugin, a
background sync, an EAS signing chain — all of it to get sleep off a phone.

The Fitbit app became **Google Health** in May 2026, and the Fitbit Web API —
sunsetting *this month* — is replaced by the **Google Health API** at
`health.googleapis.com/v4/` on standard Google OAuth2. That is a real cloud
endpoint, so the nightly feed becomes another server-side adapter next to Hevy
and Withings, running in the same cron.

Phase 3 therefore splits. **3a is the feed**: an adapter, a token flow, and
Phase 2's gate becomes reachable. **3b is the app**: push notifications and a
nicer UI, and nothing depends on it. MyFitnessPal calories are now the only
data path still needing something on the phone.

### The reason for the device is wear, not sensors

The plan already knew its own weak point — "overnight wear becomes a hard
requirement" — and the measured answer came back at **23%**: 461 nights out of
2,042. That number is what forced the readiness rework a day earlier, and no
formula fixes it. A 12g screenless pebble is a different proposition from a
Classic watch at bedtime.

So D14 is a bet, and it is written into the plan as a testable one: **the
overnight wear rate over the first six weeks says whether the switch worked**,
against a historical figure of 23%.

### What the research actually settled, and what it did not

The Air, the rename and the API are all confirmed. HRV is listed as RMSSD or
SDNN among roughly 40 data types, which probably closes **R4** — open since
the plan was written and the reason the readiness formula has an unused HRV
term. R4 drops from Medium to Low, but `HRV_AVAILABLE` stays false until a
real response shows it, because a docs listing is not a measurement.

Two things did not settle, and both are written down as unknowns rather than
smoothed over.

**R14, the serious one.** Every Google Health API scope is *Restricted*, which
needs a privacy and security review for production. An unverified app stays in
Testing status, and **in Testing, Google refresh tokens expire after seven
days.** On a daily cron that is a weekly silent breakage — exactly what §4.3's
dead-man's switch exists to catch, arriving every Monday. Whether a
single-user personal project can be verified is unknown, and it is the first
question to answer, before a line of adapter code.

**Whether third-party data reaches the cloud API.** Google's help pages say
apps connected via Health Connect sync into the Google Health *app*; nothing
found says that data is served back out of the *API*. Health Connect has no
cloud API of its own, so the chain has one unverified link.

The architecture is deliberately arranged so the second answer does not matter:
the Air records sleep, HR, HRV and SpO2 itself, so the feed is first-party
either way. **Samsung Health becomes historical only** — the export already
imported is the archive, and nothing is designed to assume more.

### Caveat on the sources

`developers.google.com` and `support.google.com` are both blocked by this
environment's egress proxy, so the API details came from search-result
summaries rather than fetched pages. Appendix B says so next to the links.
Everything specific enough to build against — scopes, token lifetimes, data
types — should be confirmed against the real documentation before it is
trusted.

---

## 14 September 2026 — the score that was best when it knew least

A review on the 11th went looking for improvements and found a bug instead:
**a morning of five hours' sleep, 71% efficiency, resting HR eight over and a
self-rating of 3/10 scored 94 out of 100, green.** Fixing it properly took the
formula apart. 211 tests passing.

### Why it scored 94

Two faults, each harmless alone.

`readiness = 100 + Σ(weight × signal)` is a deduction scale, so a component
with no data contributed **zero** — which is exactly what a component sitting
precisely on its baseline contributes. Silence and "perfectly normal" were the
same number. An empty database scored 100.

And the gate in front of it counted the wrong thing. Completeness asks how
many fields were *recorded*; scoring needs to know how many components are
*computable*. Those differ whenever a value has no baseline to deviate from,
which at 23% overnight wear is most of the time. The day scored 71.4% complete
with six of seven components silent.

### What replaced it

A weighted mean over the components that could be computed. Missing ones leave
the numerator and the denominator, so they neither flatter nor punish, and the
answer becomes "as far as sleep can tell, this is a 62" with the coverage
printed beside it.

The owner's instinct was to invert the scale — start at zero, add credit for
each measurement. That does not work, and the reason is worth recording: with
only sleep measured the attainable maximum would be sleep's share of the
weight, so a perfect night would read 13/100. Rescaling by what is available
is unavoidable, and **once rescaled, counting up from zero and counting down
from full are the same equation with the sign flipped.** There was no choice
to make, only an arithmetic identity to notice.

Coverage is now the gate, at 10%. Deliberately low, for a stated reason: he
does not wear a watch to bed and said plainly that a dashboard which goes
blank when he forgets is one that stops being opened. A lone check-in is 11.5%
of the weight and scores, marked `partial`, carrying a sentence naming what it
rests on. The only refusal left is the one that survives scrutiny — nothing
computable at all.

    A. Watch left on the bedside table, tapped 7/10   52.0  amber   30% measured
    B. Same morning, rated 3/10                       58.4  amber   41% measured
    C. Bad night measured: 5h, 71%, RHR 64, 3/10       3.0  red     74% measured
    D. Good night: 7h40, 91%, RHR 52, 8/10            87.7  green   74% measured

C and D carry identical coverage and 85 points of difference. The old scale
put both above 90.

### Three faults found while testing the fix

**Sleep debt was scored from zero observed nights.** `sleep_debt` honestly
returns `(0.0, 0)` and names the count; the caller threw the count away, so
"no debt" and "no nights" were the same number. That single null-turned-zero
is what let an empty database score at all. It now needs three nights, and a
partial fortnight is measured against a proportional ceiling — three short
nights out of three read as badly as fourteen out of fourteen, rather than a
fifth as badly, which had been quietly rewarding not measuring.

**Baselines assumed a watch worn most nights.** Fourteen observations inside
thirty days needs 47% wear sustained across the window. Measured against his
real history — 461 nights across 2,042 days — that produced a reportable sleep
baseline on **2.8% of days**. Five and a half years imported, almost none of it
usable. Preferring thirty days and widening to ninety only when necessary
takes it to **69.9%**: the same fourteen real observations, no interpolation,
simply no longer also demanding they be recent. The cost is reported rather
than hidden — `span_days` says how far back they reach, a median of 62.

**The self-rating counted for nothing for a fortnight.** The field he is asked
for every single morning, and the one the check-in form was built for three
days earlier, contributed zero until fourteen check-ins existed. A 1-10 rating
is the one metric that means something in isolation — a 3 is low by the
scale's own definition, not by comparison — so it now falls back to the
scale's anchor, is flagged as anchored, and is superseded the moment his own
median exists. The anchor of 7 is a prior and is written down as one.

### What this cost elsewhere

The bands moved: a mean is more sensitive around neutral than a sum, so half
an SD down on two metrics costs seven points where it used to cost fifteen,
and green starting at 70 left an ordinary day flickering on the boundary.
Green now starts at 65.

`_redistribute_hrv_weight` is gone. It hand-spread HRV's weight across sleep
and resting HR so a missing HRV would not shrink the score; the mean does that
for every component at once, and proportionally rather than by a rule that
knew about one of them. HRV's absence still caps confidence at `reduced`,
because the plan calls that formula a fallback and it should not present as
the complete one.

### Recorded, not built

`docs/comments-to-revisit.md` now exists for things noticed and deliberately
skipped — the import's 61M-comparison hot loop, `no_watch` being collected and
never used, `WEIGHT_FRESHNESS_DAYS = 1`, sleep going stale between exports.
The maybe pile, kept separate from `outstanding.md`, which is work that is
going to happen.

And **F2, the long record**, is in the plan at §14.1: coverage by month,
weight against training volume, sleep by weekday and season, resting HR over
years, with an export behind it to hand to a GP. The argument for it is that
the sparser the daily data, the more the value sits in the long view — a
five-year weight trend does not care which particular nights are missing.
Deferred, with the note that unlike everything else in that section it needs
no new integration, no device and no elapsed time.

---

## 11 September 2026 (later) — the export goes in, and is wrong four times first

The parser met the real export and four assumptions died. Every one of them
would have produced a dashboard rather than an error. 198 tests passing.

### The header is not the widest line, and never was

The real sleep file has a **62-field header above 63-field data rows** — a
trailing comma on every row. The rule in place, "the candidate line whose
width the data rows agree with", therefore scored the header at zero and a
data row at 460, elected the data row, and produced a table whose column
names were `0`, `0.0`, `UTC+0000`, `VAbvgF796r` and a uuid. It parsed 460 rows
and read none of them.

That was the fourth width-based header rule to fail on this format, so width
is gone. Column names are identifiers; values are numbers, timestamps,
offsets and uuids. A line whose non-empty cells are 80% identifier-shaped is
the header, and that distinction does not care whether the widths line up.

### The timestamps are UTC, and the inference said local

`day_time = '2021-05-04 00:00:00.000'` during BST established that the
pedometer file is local midnight, and that got generalised to the export. It
is wrong. The sleep file stores UTC: 0.14h residual against 0.86h, measured
across the clock change. **The export mixes conventions per file**, which is
the whole reason the check was built instead of the inference trusted.

Two bugs stood between the check and that answer. The seasonal pair was taken
as `min(offsets)` and `max(offsets)`, which on an export containing holidays
compared a week at UTC-0500 against a long weekend at UTC+0900 — six records
against three, with several hundred GMT and BST nights ignored in between. It
now takes the two offsets an hour apart holding the most records, which is
what a daylight-saving step is and a pair of holidays is not.

Then the comparison itself moved from whole seasons to three weeks either
side of a clock change. Bedtimes drift with the season by something
approaching an hour — the size of the effect being measured — and the
direction depends on the sleeper: later in summer biases towards `local`,
earlier biases towards `utc`. Across six weeks the drift is minutes and the
error is still the full hour, because one is gradual and the other is a step.

### A check that could not do its job

159 nights of resting HR out of 461 sleep sessions looked like heart rate
might use a different basis again. A check was written to settle it by
overlap, and then an export was built with sleep in UTC and heart rate in
local to confirm the check worked. **It did not** — both readings scored 730
of 730, because an hour's shift on a seven-hour window leaves nearly every
reading inside it.

It was deleted rather than shipped. A check that reports agreement on a file
that demonstrably disagrees is worse than no check. The same insensitivity is
what makes the inherited assumption cheap, and that reasoning is now written
down where the next person will look. In its place the importer reports what
is knowable: 449 nights have some heart rate, 162 have the twelve a
percentile needs, and a typical night has nine. The watch, not the parser.

### One day, several devices

The import then crashed on a UNIQUE violation on `steps:2021-04-15`. The
pedometer file carries **about 2.7 rows per day**, one per device that counted
— 2,735 of 5,229 rows shared a key. The session does not autoflush, so
`store_raw` could not see a row queued moments earlier and both reached the
database together.

The crash was the small half. `parse_steps` had been keeping whichever row
came last, which is arbitrary: it can report a pocketed phone's 2,964 steps
for a day the watch saw 11,402. That would never have thrown. The largest
count now wins — the device that saw most of it — with the rest of the day's
figures from the same row. Summing was rejected because it counts one walk
once per device.

### The bookkeeping could not record its own failure

Underneath all of it, `sync_run` was broken in a way that matters beyond
Samsung. A failed flush leaves the session refusing every further statement,
so setting the run to `failed` and committing raised `PendingRollbackError`:
the run stayed `running` and the original error was buried under a second
traceback. **That is the silent ingestion failure the bookkeeping exists to
prevent**, in code the Hevy adapter shares, and the invariant had no test.

It now rolls back before recording, onto a run row committed before the work
starts so it survives the rollback. A process killed mid-sync leaves a
`running` row instead of no evidence. `tests/test_ingest.py` covers success,
failure, a constraint violation and the rollback; the last two fail against
the previous code, which was checked rather than assumed.

### What it bought, and what it did not

461 sleep sessions, 1,950 days of steps, 63 weight readings and 159 nights of
resting HR, Feb 2021 to Sep 2026. Four of the seven completeness fields.

**Four of seven is 57.1% against a 60% floor.** A fully-measured night still
reads `insufficient_data`, 2.9 points short. Samsung's weight would be the
fifth but `WEIGHT_FRESHNESS_DAYS = 1` and there are 63 readings across five
years. So the binding constraint is now the check-in form — one subjective
field, typed by hand, worth more to the score than any further integration.

461 nights across 5½ years is roughly one night in four. That wear rate, not
the parser, is what the baselines have to live with.

---

## 11 September 2026 — the Samsung export, and proving the timezone

The export is the only route to the four completeness fields readiness is
starved of, so this session built the parser for it. The interesting part is
not the parsing; it is that the parser **refuses to run until it has proved
which clock the timestamps are on**. 184 tests passing.

### The question that had to be settled before writing anything

Samsung writes wall-clock times in one column and the UTC offset in another,
and never says whether the clock reading is local or already-UTC. Both
readings parse. Both produce a plausible dashboard. They differ by exactly one
hour for the half of the year the offset is not zero, which is enough to move
a night onto the wrong day, and they agree perfectly in winter — so the wrong
choice is invisible for months and then quietly corrupts every sleep baseline.

Inference pointed at local (`day_time` is exactly local midnight during BST),
but inference is what silent failures are made of. `detect_timestamp_basis`
settles it from the data instead: take the bedtimes, group them by offset,
convert each way, and ask which reading leaves the seasonal groups agreeing.
A human's bedtime does not jump an hour every March. Whichever reading makes
it look like it did is the wrong one.

Against the 555-night export shape, reading as local leaves a 0.02h seasonal
gap and reading as UTC leaves 1.02h. The importer prints both numbers, uses
the winner, and **returns 2 and writes nothing** when the data cannot settle
it — one season only, too few nights, or bedtimes scattered enough that an
hour is not distinguishable from noise. `--basis` overrides it for someone who
has established the answer another way.

### Five bugs, four of them silent

The header line was the theme. Samsung puts a package-and-version line above
the real header, so "the line with the most fields wins" picked the metadata
line; agreement with the data rows below fixed that, until a three-column
heart-rate file had a metadata line the *same width* as its header and parsed
zero samples. Detecting the package-and-version shape explicitly fixed that,
and then a `>=` tie-break let a data row outscore the header and sleep parsed
zero rows. Each of these produced a parser that ran happily and returned
nothing, or returned nonsense.

The other two: a `width < 2` guard silently dropped single-column files, and
the circular difference between 23:00 and 00:00 came out as 23 hours instead
of 1, which would have rejected a perfectly good export as "scattered".

### What it reads, and what it deliberately does not

Sleep sessions, daily steps, weight with body composition, and heart-rate
samples. Duration is computed from the two timestamps rather than read,
because the pre-2024 records carry no duration field at all. Efficiency comes
from `original_efficiency` and falls back to `efficiency` with **zero treated
as absent** — the real export writes `efficiency = 0.0` on every pre-2024
session, and storing that zero would put a fabricated 0% into a column the
metrics engine reads as measured.

Resting HR is not in the export. It is derived — `resting_hr_from_samples`
takes the 5th percentile of the readings falling inside each sleep session,
and returns None below twelve samples rather than a figure resting on three.

Source rows are retained verbatim for sleep, steps and weight, per the raw
retention rule. Heart-rate readings are the one knowing exception: three years
of a worn watch is hundreds of thousands of rows, and resting HR is
recomputable by re-running the importer against the export file. That is
written down in `RAW_SKIPPED` rather than left as an omission someone finds
later.

Not ingested yet: HRV (values are buried in `binning_data` JSON blobs), sleep
stages as a series, stress, SpO2, skin temperature, respiratory rate, floors,
and Samsung's own exercise records.

### Still unproven

All of this has run against an export shaped like the real one, not the real
744 MB export itself — that is the next thing, `--dry-run` first. And the
timezone verdict is only as good as the export's own bedtime regularity; the
refusal path exists because that is not guaranteed.

---

## 10 September 2026 — the data reaches a screen

The morning's session got real Hevy data in. This one put it in front of a
reader, and found that most of what was wrong was in the parts nobody had
looked at yet. 163 tests passing.

### The screen exists

`GET /ui` serves the Glacier reference from the backend, fetching
`/api/v1/today` on load. The four hand-written mornings are gone — an example
on a screen whose job is showing what is yours is worse than a blank — so the
live view is the only view. The page is unauthenticated because it is markup;
the browser holds the bearer token for the data behind it.

**Pointing the design at real data broke it four times**, none of which the
four designed mornings could expose, because all four carry data in every
field:

1. `renderTraining` called `acwr.toFixed(2)` unguarded. ACWR is null more often
   than not for this account, so the live view threw on arrival.
2. `renderWeight` took `vals[vals.length - 1].toFixed(1)` on an empty series
   and aborted the whole render, leaving the page half-drawn — which is why
   the first screenshot showed a mix of correct and stale values.
3. `renderRhr` on an all-null series computed `Math.min` of nothing, put NaN
   in a circle's `cy`, and the browser rejected it.
4. The intro roll-up animation writes `#score` every frame for 1.1s after
   load, counting to a hard-coded 62. Click into a no-score morning inside
   that window and it painted 62 back over the em-dash — **a fabricated
   readiness score sitting under a "no score" label**, on the screen whose
   entire purpose is to never do that. It had been there since the design was
   drawn on 3 September and only surfaced because an automated click was
   faster than a human usually is.

### A splice that duplicated half the page

Removing the design-language section searched for `"MyFitnessPal"` to find the
end of a row and matched an earlier occurrence — "MyFitnessPal does not sync
macros", further up. End landed before start, so `t[:a] + t[b:]` concatenated
the overlap instead of removing it, and the entire tile block rendered twice.

Nothing threw. `getElementById` returns the first match, so the live render
updated one copy and left the other showing the design's hand-written values:
a second set of entirely plausible tiles. Two things stop it recurring: every
splice now searches for its closing marker from the opening marker's position
and asserts `end > start`, and **a test asserts every id on the page is
unique**. The assertion caught the same class of bug again during the rebuild.

### Layout, and what the screen refuses to claim

Twelve cards of equal weight meant nothing said where to look. Split into
*This morning* — readiness, brief, yesterday's session, weight, sleep trend —
and *The record* below it. Three new tiles drawn and marked Coming soon, every
value an em-dash: sleep consistency as nights-at-target out of seven rather
than a mean, which would hide exactly the inconsistency worth seeing; steps;
and energy balance as two bars on one shared scale, because the gap between
them is what is being read.

Everything invented is gone — a "day 12 of 42" phase counter, a 93% supplement
adherence rate, an 11-day streak, an 87% completion figure, four made-up sync
timestamps. What is not built is greyed and labelled rather than hidden. Dates
are DD-MM-YYYY; the API keeps ISO because it sorts unambiguously.

### The metrics engine, against real data for the first time

`scripts/verify_metrics.py` runs the engine over the real backfill. What it
found, on 274 workouts:

- **The load-definition problem, confirmed by the owner's own workout titles.**
  A 13.0x spread between heaviest and lightest session against 4.1x in
  duration. The three heaviest are "Big leg day + abs", "Legs + abs", "Legs";
  the three lightest "Quick chest day", "Quick chest day", "Quick Push day".
  "Legs + abs" ran 18% longer than "Quick chest day" and scored 8.8x the load.
- **ACWR flagged 27% of assessable days**, 27 of them at the full penalty, in
  consecutive clusters — consistent with leg days bunching, not with
  overreaching.
- **ACWR could not compute on 638 of 1109 days.** It needs 8 training days per
  28; the history averages 1.69 sessions a week. It will be unavailable more
  often than not, so readiness leans on sleep and subjective more than the
  design assumed.
- **Volume progression is flat.** Every slope is under half a percent of the
  weekly mean — `+13 kg/wk` on calf extension reads like progress and is 0.19%.
- **The ACWR-of-4.0 guard fired on real data.** On 8 September acute was 50.24
  against chronic 12.56 — exactly 4.0, the spurious value the 3 September
  session fixed against fixtures. It returned None, because only one training
  day sat in the window.

### Qualifying a number rather than suppressing it

The tempting response to a 27% flag rate was to withhold ACWR while load is
volume-derived. The owner's call was the better one: *build for the data you
intend to feed, not the data you have.* RPE logging has started, and in a
month the same code path carries the definition it was designed for.

So `load_quality` reports which definition produced the chronic window —
`rpe_based`, `volume_based`, `mixed` — and travels with acute, chronic and
ACWR through the §9.1 contract, `/today`, and a new `daily_metrics` column so
a stored ratio is still readable a year on. **The caveat wording lives in
tested code**, and prompt rule 4 requires the model to reproduce it verbatim
rather than compose its own: a caveat the model writes is a caveat it can
soften on a day it wants a cleaner story. Migration 0002, nullable with no
backfill — rows computed before the column existed genuinely do not know their
basis, and backfilling "volume_based" would be an assumption dressed as a
record.

### The recovery figure (§14.1 F1)

Two schematic silhouettes beside the readiness gauge, each muscle group shaded
by how recently and how hard it was worked. The data path already existed:
every set carries an `exercise_template_id`, and Hevy's
`/v1/exercise_templates/{id}` returns its own muscle-group vocabulary. A new
`exercise_templates` table caches them (migration 0003); the sync walks only
the distinct ids present in `workout_sets`.

**Four states, no percentage.** "Chest: 60% recovered" reads as measured and is
not. Windows vary by group — 36h for biceps and calves against 72h for quads
and the posterior chain — and stretch with volume relative to the owner's own
median for that group, which *is* a measurement. On real data the separation
shows: triceps read likely ready while chest is still recovering from the same
session. A group never worked reports "not trained", not "ready".

**The existing "no time series" test earned its place.** `muscle_recovery` is
seventeen rows of hours and volumes, and it went into `build_brief_input`
before the test caught it. It now reaches `/today` only.

Two follow-ups came from the owner looking at it. The empty-figure note blamed
setup regardless of cause, so a genuine rest week would have read as a broken
install; `muscle_recovery_status` now distinguishes unmapped, no recent
training, and ok. And the template sync — 166 distinct exercises on this
account — gave a silent minute of terminal and committed nothing until the
end, so an interrupted run discarded everything. It now reports progress and
commits every 20; verified by killing a run on its 55th request and watching
40 templates survive and the re-run resume.

### The finding that decides what happens next

Readiness needs 5 of 7 fields to clear the 60% completeness floor. Samsung
Health supplies 4 of them — sleep duration, sleep efficiency, resting HR,
steps. Withings, MyFitnessPal and the check-in supply one each.

**Without Samsung the ceiling is 3 of 7, or 43%.** Every other source
connected, a perfect check-in streak, and the score still reads
`insufficient_data` forever. With Samsung plus any one other source it works.

The dashboard is a good training dashboard. It is not yet a health dashboard,
and no further code changes that.

### Also

`docs/outstanding.md` records everything deferred, grouped by what would
actually unblock it — six items are free signups, three cannot be compressed
by writing any code. Merging to `main` on green is now the working agreement:
three times work sat on a feature branch while the owner was on `main`, and
each time the symptom was a confusing failure rather than an obvious one.

Removed `metrics-report.txt`, committed before the gitignore pattern covering
it landed — gitignore does not untrack a tracked file.

### Next

The Samsung Health export, or the check-in form and somewhere to host it so
the seven-day clock starts. Neither is blocked by code.

---

## 10 September 2026 — the Hevy adapter, verified against the real API

**The first session with real data in it.** 274 workouts, 4331 sets, 31 July
2023 to 8 September 2026. The adapter had only ever been checked against a
hand-written fixture; this replaces that with the account's own history and
fixes what the comparison exposed. 139 tests passing.

### Where the project stands

- **Keys held: Hevy only.** No Withings, Supabase, Anthropic or Resend.
- Overnight watch wear is patchy; the Samsung Health export has not been run.
- Nothing is deployed.
- **Phase 1's gate is still open.** It needs seven consecutive days of
  check-ins *and* a full Hevy and Withings import. Hevy's history is now
  proven importable but has not been imported into a real database, and
  Withings cannot start without credentials. The gate is blocked on key
  collection and a host, not on code.

### The build environment cannot reach Hevy

`api.hevyapp.com` is refused at this environment's egress proxy (403 to
CONNECT). Not a code fault and not something to route around, so the
verification runs on the owner's machine instead. `scripts/verify_hevy.py`
exists for that: it packages the whole check — count against
`/v1/workouts/count`, field-by-field conformance across the entire history,
the volume arithmetic reproduced by hand, date attribution near midnight and
across a BST/GMT boundary — so it produces the same report wherever it runs,
and captures a scrubbed fixture with `--write-fixture`.

That split is worth keeping in mind for Phase 3: **anything needing a real
credential has to run somewhere the credential and the network both are.**

### What the real payload said

Every field the adapter reads exists on every record, with the shape it
expects. The count agrees at 274, there are no duplicate ids, and the volume
hand-check reproduces exactly: 20290.0 both ways on the 7 April legs session,
with 500.0 of warm-up excluded.

Three places reality differed from the fixture, and one from the spec:

1. **Timestamps carry `+00:00`, not `Z`.** The adapter handled both; the
   fixture had been testing a format the account never sends.
2. **`description` and `notes` are `""`, never null.**
3. **`weight_kg` is null on 463 of 4331 sets** — 11%, all bodyweight work.
4. **The published OpenAPI spec is wrong.** It documents `supersets_id`; the
   API sends `superset_id`. Nothing reads it, but it is a reminder that the
   spec is not the territory, which is the whole reason this was checked
   against the live API.

### The finding that mattered

**RPE was null on all 4331 sets.** The owner had never logged it. So
`session_load`'s primary `duration x RPE` branch was unreachable, and three
years of training load came entirely from the volume fallback — with
`Workout.perceived_exertion_1_10` never written by anything, so even a
logged RPE would have gone nowhere.

That is worse than "the second-choice definition". Volume load is dominated
by absolute weight, so it systematically overweights machine leg work:

| Session | Volume load | As duration x RPE |
|---|---|---|
| Upper body, 8 Sep (39 min) | 5024 kg → 50 units | ~313 units |
| Legs, 7 Apr | 20290 kg → 203 units | ~320 units |

Volume ranks the leg day four times harder. It was not. The signal driving
ACWR — and through it readiness — has largely been *"did he train legs?"*
rather than *"how hard did he train?"*. Compounding it, **136 of 274 sessions
(half) contain unweighted sets volume cannot see at all.**

The owner has started logging RPE as a result. That is the fix; no estimation
of bodyweight loads is planned, because `duration x RPE` does not care
whether the load was external, and an estimate built from a bodyweight series
that does not exist yet would be machinery producing a guess.

### Changes

- **Session RPE is aggregated and stored** — the mean of working sets that
  carry one, warm-ups excluded. Not Foster's sRPE; close enough to drive the
  same formula and what per-set logging supports.
- **`_volume_kg` returns None, not 0.0**, when no working set has both a
  weight and reps. Its own docstring said an unquantifiable session must not
  count as zero load; the guard was defeated by the adapter never producing a
  None. As it happens **0 of 274 sessions hit this** — a latent bug, not a
  live one, and worth fixing before a bodyweight-only session abroad finds it.
- **Blank descriptions store as null.**
- **ACWR is withheld across a change of load definition.** The fortnight after
  RPE logging starts, the acute window is RPE-based while the chronic window
  is still volume-based, so the ratio measures the units changing rather than
  the training. Simulated on the real training shape: ACWR 2.80 in week one
  (a full 9-point readiness penalty), 1.75 in week two, back to normal by
  week four. Two weeks of the score marked down for a spike that never
  happened, and a brief obliged to explain it — R2 arriving through the back
  door of a units change. `acwr` now takes a per-day set of load bases and
  declines when the chronic window holds more than one, which is the pattern
  it already used for a too-short window or a zero chronic load.
- **The fixture is eight real scrubbed workouts**, chosen to carry between
  them a warm-up, bodyweight sets, fractional weights, a near-midnight start,
  and one session each from GMT and BST. The six fixture-based tests are
  rewritten against real numbers, and the delete test now proves the other
  seven survive — something a one-workout fixture could not test.

### Two process notes

The first version of `verify_hevy.py` **crashed on Windows** before printing
anything useful: PowerShell writes cp1252, Hevy titles carry emoji, and the
volume hand-check prints titles through `repr()`. Reproduced under
`PYTHONIOENCODING=cp1252` and fixed by forcing UTF-8 on stdout. The report
died on a decorative character rather than on anything it measured.

The raw report files were committed alongside the fixture by accident. They
carry the **unscrubbed** payload — real ids, titles and notes — which defeats
the point of scrubbing the fixture beside them. Removed and gitignored; they
remain in the history of `caba164`, which is cosmetic in a private repo but
worth knowing.

### Next

Withings needs credentials before Phase 1's gate can move, and the Hevy
import needs somewhere to run with both the key and network access. The
readiness score has still never seen real data end to end — every number in
it remains checked against fixtures and simulation.

---

## 3 September 2026 — UI preview made deployable and explorable

`docs/ui/glacier-today.html` now renders from a data object rather than fixed
markup, with a switcher for four mornings: accumulating, nothing unusual,
overreached, and watch-not-worn. The last one is the point of the exercise —
`insufficient_data` renders as an absent arc, an em-dash and "no score", with
both the sleep and resting-HR tiles showing gaps and the brief refusing to make
a training recommendation. Claiming the design handles that is cheap; looking
at it is not.

`netlify.toml` publishes `docs/ui` as a static site. **The backend cannot go on
Netlify** — there is no Python runtime for Netlify Functions — so FastAPI still
needs Fly.io or Render per §4.3.

Two bugs found by rendering the states rather than reasoning about them:

1. **An unscoped `.bar` rule.** The sleep chart's `.bar{flex:1}` also claimed
   the brief caveat's 2px amber rule, stretching it into a wide filled block.
   Scoped to `.bars .bar`. It had been wrong since the design was first drawn.
2. **A zero-length arc still paints its round cap**, leaving a coloured dot on
   the no-score gauge that read as a very low score. The arc is now hidden
   outright when there is nothing to draw.

And one found by running the suite on a machine that finally had a real key in
`.env`: **the tests were not hermetic.** `Settings` reads `.env`, so a live
`HEVY_API_KEY` turned two "this source is unconfigured" assertions red locally
and nowhere else — CI has no `.env` and stayed green. The dotenv path is now
`ENV_FILE`, which `conftest.py` sets to empty. Verified both ways: 126 pass
with a populated `.env` present and with none at all.

---

## 3 September 2026 — Phase 2: metrics engine, readiness, the brief

**Status: Phase 2 code complete. The phase *gate* is not met and cannot be met
by writing code — it needs seven consecutive days of an accurate brief against
real data.** 126 tests passing.

### What exists

- **`app/metrics/`** — pure functions, no database, no clock. Baselines
  (30-day rolling median, withheld below 14 observations, D3 wear-bias guard),
  derived metrics (sleep debt, midpoint variance, session/acute/chronic load,
  ACWR, weight EWMA and trend, protein g/kg, completeness, volume
  progression), and the §6.3 readiness score with its component breakdown.
- **`app/services/metrics_engine.py`** — the only module that knows both SQL
  and the metrics. Windows the data, drops excluded days, persists
  `daily_metrics`, and renders the §9.1 input contract.
- **`app/ai/`** — the phase-locked system prompt, the structured output
  contract, the Anthropic call, and the traceability guard.
- **`app/services/email.py`** — the brief rendered in the Glacier language,
  restricted to what mail clients support.
- **`scripts/daily_brief.py`** and a step in the sync workflow — the 06:30 job,
  idempotent, with meaningful exit codes.
- Endpoints: `POST /brief`, `GET /brief/{day}`, `GET /brief/input/{day}`,
  `GET /brief/{day}/preview`, `POST /brief/{id}/feedback`, `GET /metrics/{day}`.
  `/today` now carries real readiness.

### The traceability guard

Plan §14's Phase 2 gate is "every number in it traces back to the input JSON".
That is now checked in code rather than trusted: every numeric token in a
generated brief is matched against the input snapshot, with one retry naming
the offending figures, and the brief is stored flagged if it still does not
trace. A unit conversion counts as a violation — "5h42m" from a stored 342
minutes is arithmetic the model was told not to do, and it reads exactly like
a measurement. The guard caught two of its own test fixtures during the build.

### Four things found by looking at real output

1. **ACWR of 4.0.** Four sessions in an otherwise empty month gave a ratio
   that was arithmetically correct and meaningless. ACWR is now withheld until
   the chronic window holds at least eight training days.
2. **A single bad reading took a third of the scale.** Z-scores are now
   clamped at ±2 SD rather than ±3: past two, the difference between bad and
   very bad on one metric is not information the score should act on.
3. **SD floors were too tight.** A 15-minute floor on night-to-night sleep
   variation made an ordinary short night a three-sigma outlier. Raised to
   values that are plausible minimums rather than implausible ones.
4. **Two definitions of "weight trend".** The Today endpoint had its own
   7-vs-7 average difference, contradicting the engine's EWMA slope. Deleted;
   there is now one definition. Supplement adherence had the same problem and
   moved to `app/services/supplements.py`.

### Decisions worth recording

- **Readiness lands in Phase 2, not Phase 4.** §14 lists it under Phase 4, but
  the §9.1 input contract carries `readiness`, so the brief cannot be built
  without it. Noted in the plan.
- **Weights are provisional and configurable.** Scaled so a single bad night
  stays amber while an accumulating pattern goes red. Nothing in six weeks of
  baseline data can validate them.
- **The phase never promotes itself.** `BRIEF_PHASE` is config and stays on
  `baseline` until deliberately changed. A brief must not start making causal
  claims because six weeks elapsed.
- **No template fallback.** With no API key the job fails loudly rather than
  sending something that looks generated.

### Outstanding, not code

1. Keys: Anthropic, Resend, plus the Phase 0 set still outstanding.
2. **The readiness score has never seen real data.** Every number above was
   checked against seeded fixtures and a simulation with realistic variance.
3. Phase 1's gate is still open: seven days of check-ins, and a full Hevy and
   Withings import.

### Next session

Phase 3 is gated on Phase 2's acceptance test, so the useful work before then
is the eval set (§9.4: ~15 hand-picked days including a no-watch day and a
missing-macros day) and the Expo app's Today screen against `docs/ui/`.

---

## 3 September 2026 — UI design language locked

**No application code changed. Documentation and one static reference file.**

Settled the visual direction before Phase 2 starts, so the brief renderer and
the Expo app are built against a decided language rather than an improvised one.

- **Plan §10.3 — "Glacier"** added: colour tokens for both themes, the three
  type roles, materials and grid, component specs (readiness gauge, brief,
  metric tile, micro-charts, gaps, chips, phase pill), motion and accessibility.
- **`docs/ui/glacier-today.html`** — the reference implementation. The Today
  screen from §10.1, in both themes, rendered from the §9.1 example payload
  (readiness 62 amber with reduced confidence, sleep 342 min against a 430
  baseline, RHR 58 vs 52, ACWR 1.27, weight EWMA 84.2). Static HTML, no build
  step. Also published as an artifact:
  <https://claude.ai/code/artifact/6cd4ddae-46e7-4fe4-b70a-f7f37dd87b95>

### The decision that matters

Four of the invariants are now enforced by the visual system rather than left
to the copy: a missing night is a hatched dashed column and an unavailable
metric is an em-dash with its reason; the phase pill is permanent chrome; status
colour is separated from the accent and always carries its word; every figure is
tappable to its definition. `insufficient_data` has a designed appearance — the
empty dashed arc — which is what stops a placeholder score ever being invented
for it.

### Not yet designed

The other six screens (Trends, Training, Body, Supplements, Experiments, Data
health) inherit the tokens but have no composition. The phone layout is
specified as an ordering, not drawn. Both are Phase 3 work.

---

## 3 September 2026 — Phase 0 + Phase 1 backend

**Status: both phase gates met, with one caveat (below).**

### Decisions taken this session

| Item | Decision |
|---|---|
| O1 — frontend | Expo, one codebase (plan default) |
| O2 — nutrition app | Stay on MyFitnessPal, calories only. Protein reports as unavailable. Revisit before Phase 3. |
| O3 — sleep target | 7h30 (450 min), in config as `SLEEP_TARGET_MIN` |
| Keys | None held yet — built against fixtures; adapters are live code, not stubs |
| Scope | Backend only. No UI this session. |

### What exists

FastAPI backend, 41 tests passing.

- **Schema** — all 20 tables from plan §5.2, one Alembic migration
  (`0001_initial_schema`). Verified to build and tear down on SQLite and to
  render correct DDL for Postgres (JSONB, `TIMESTAMP WITH TIME ZONE`).
- **Ingestion** — raw payloads retained forever with provenance; idempotent
  upsert on `(source, source_record_id)`; `sync_runs` bookkeeping.
- **Hevy adapter** — paged backfill and incremental sync via
  `/workouts/events`, handling both update and delete events. Volume load
  excludes warm-up sets.
- **Withings adapter** — OAuth2 authorisation-code flow, `Measure - Getmeas`
  parsing with unit-exponent scaling, and rotated-refresh-token persistence.
- **Check-in API** — partial submissions accepted, all 13 confounder tags live
  from day one, 3-day backfill flagged `submitted_late`, streak and 30-day
  completion rate.
- **Supplements** — the eight-item stack seeded with dated protocol-start
  rows, schedule-aware daily checklist, protocol change log.
- **Data health** — per-source staleness, overnight wear rate, check-in
  completion. Failed syncs are recorded, not swallowed.
- **Ops** — CI workflow, daily-sync cron with a Healthchecks dead-man's
  switch, gitleaks pre-commit hook, Dockerfile, full JSON export endpoint.

### Two bugs found and fixed during the build

1. **Naive datetimes from SQLite.** Postgres preserves the offset, SQLite
   discards it, so any comparison against an aware datetime raised. Fixed with
   a `TZDateTime` type decorator that normalises on the way in and out — the
   test database now behaves identically to production, and a naive datetime
   reaching the database raises loudly rather than being silently stored.
2. **Adapter construction outside the sync-run bookkeeping.** A missing API
   key produced a bare 500 with no `sync_runs` row, so the Data Health screen
   would have reported nothing wrong. Adapters are now constructed inside the
   run. This is exactly the R6 failure mode.

### Caveat on the Phase 0 acceptance test

The plan's Phase 0 gate is "`alembic upgrade head` builds the full schema **and
a health-check endpoint returns 200 in production**". The first half passes.
The second cannot until a Supabase project and a host exist.

### What is deliberately absent

`sleep_sessions`, `heart_metrics` and `activity_daily` have tables and no
writer. They fill in Phase 3 via Health Connect. Creating them now means the
migration history does not need rewriting later.

`/api/v1/today` returns `readiness: null` rather than a placeholder score.
Phase 2 owns the metrics engine.

### Outstanding, not code

1. Phase 0 key collection: Hevy (`hevy.com/settings?developer`), Withings
   developer app, Supabase project, Anthropic API key, Resend, Healthchecks.
2. **Run the Samsung Health export.** Ten minutes, does not expire, and it is
   what makes baselines meaningful from week one rather than week six.
3. **Start wearing the watch overnight, 5+ nights a week.** The baseline clock
   starts when the data does, not when the code ships.

### Next session

Phase 2: the metrics engine (baselines, deviations, sleep debt, training load,
weight EWMA), the readiness score with component breakdown, the daily brief
against the §9 contracts phase-locked to `baseline`, and email delivery.
