# Personal Health Dashboard — Requirements & Build Plan

**Owner:** Ricky Mameli
**Version:** 1.0 — decisions locked, ready to build
**Date:** 3 September 2026
**Supersedes:** v0.1 (3 September 2026)
**Purpose:** Single source of truth for building the dashboard.

---

## 0. Locked decisions

| # | Decision | Answer | Consequence |
|---|---|---|---|
| D1 | Nutrition app | **MyFitnessPal** | Calories automate via Health Connect; **macros do not** — see §3.4. This is the weakest link in the stack. |
| D2 | Hevy Pro | **Yes, owned** | Hevy REST API available from day one. Phase 1 unblocked. |
| D3 | Watch | **Galaxy Watch8 Classic**, worn overnight only sometimes | Sleep is the backbone of the system. Overnight wear becomes a hard requirement during baseline — see §3.3. |
| D4 | Budget | **Comfortable with running costs** | Design for correctness over penny-pinching, but §4.4 still lands at roughly £0/month plus Claude API usage. |
| D5 | Delivery | **Email or WhatsApp first; wants a real app eventually** | Architecture pivots to a single React Native codebase — see §4.2. Email for v1, native push once the app ships. |
| D6 | Alcohol / caffeine | **Not now; add after beta** | Tags stay in the check-in (zero cost, one tap); quantified fields deferred. Explanatory power is capped until then — see §7.2. |
| D7 | Smart scale | **Withings, syncing to Health Connect** | Use the **Withings API directly** — free tier, OAuth2 — rather than routing through Health Connect. See §3.2. |
| D8 | 6-week baseline before causal claims | **Accepted** | Phase model in §2.2 stands as written. |
| D9 | Historical backfill | **As much as possible** | One-off Samsung Health export for deep history; Hevy and Withings backfill via API. See §3.5. |
| D10 | Access model | **Cheapest and fastest** | No custom domain, no public registration. Single-user magic-link auth on free hosting tiers. See §13. |

### 0.1 What changed from v0.1

1. **Architecture pivot to one React Native codebase (Expo).** You want an app eventually. That single fact resolves the hardest problem in the project, so it should shape the build from day one rather than being bolted on later.
2. **Health Sync + Google Drive CSV demoted from primary to fallback.** Because the eventual Android app can read Health Connect directly via `react-native-health-connect`, the CSV bridge becomes a contingency rather than the plan.
3. **Withings promoted to a first-class direct integration.** Its public API has a free tier; going direct is more reliable than reading scale data second-hand through Health Connect.
4. **Delivery simplified to email, then native push.** WhatsApp is disproportionate effort for this job — see §11.
5. **MyFitnessPal's limits made explicit.** It syncs calories to Health Connect but not macros, and protein is central to your recomposition goal.

---

## 1. Problem statement and success criteria

### 1.1 The problem

Health data is fragmented across Samsung Health, Hevy, MyFitnessPal and Withings. None of them talk to each other, none of them know about supplements, and none of them know how you actually felt. The result is a lot of measurement and very little insight.

### 1.2 What "done" looks like

| # | Criterion | Measurable test |
|---|---|---|
| S1 | You read the daily brief most mornings | ≥ 70% open rate over a rolling 30 days |
| S2 | You complete the subjective check-in most days | ≥ 80% completion over a rolling 30 days |
| S3 | The brief is judged useful | ≥ 60% of briefs rated "useful" via in-app feedback |
| S4 | It surfaces something you did not already know | ≥ 3 validated insights logged over 6 months |
| S5 | Manual data entry stays under 60 seconds/day | Timed self-report |
| S6 | Overnight watch wear during baseline | ≥ 5 nights/week for the first 6 weeks |

**S2 and S6 are the project's centre of gravity.** Objective data arrives for free only if the watch is on your wrist. Subjective data never arrives for free. Without both, the "why do I feel rough today?" capability is dead on arrival, and every design decision below is weighted toward keeping their friction near zero.

---

## 2. Review of the original brief

### 2.1 What is right

- **Multi-source aggregation is the correct foundation.** The value is in the joins — sleep against training load against how you felt — not in any single stream.
- **Subjective input is the right instinct and most people skip it.** Wearable-only dashboards can tell you your HRV dropped; they cannot tell you it mattered.
- **Supplement tracking is underserved.** No mainstream app does it well alongside training and recovery data.
- **Daily cadence is right.** Weekly is too coarse to act on, real-time is noise.

### 2.2 What needs to change

**C1 — "Tell me why I don't feel 100%" will not work on day one, and you should not build as if it will.**

You are an n=1 sample. On day 30 you have roughly 30 paired observations across a dozen candidate variables. Any "cause" reported at that point is a story, not a finding. It will sound confident and it will frequently be wrong, and catching it being confidently wrong in week two is the fastest route to abandoning this project.

You have accepted a 6-week baseline (D8), so this is now locked in as a three-phase model:

| Phase | Window | Language permitted |
|---|---|---|
| `baseline` | Weeks 0–6 | Facts and deviations only. "You slept 5h42 against a 7h10 baseline; resting HR was 6 bpm above your 30-day median." **No causal claims of any kind.** |
| `associative` | Weeks 6–16 | Associations with a stated sample size and an explicit hedge. "Across 43 days, your worst-rated mornings follow nights under 6h roughly twice as often as your best. Suggestive, not established." |
| `experimental` | Week 16+ | Causal claims permitted **only** for a completed N-of-1 experiment with a computed effect size. |

The phase is enforced in the prompt contract (§9.2), not left to the model's judgement.

**C2 — The LLM must never do the arithmetic.**

The single most important architectural decision here: split the system into a **deterministic metrics engine** and a **narration layer**.

- The metrics engine computes every number — baselines, deviations, sleep debt, training load, readiness — in tested code. Reproducible and auditable.
- The LLM receives a compact, pre-computed JSON summary and does only what it is good at: prioritising, explaining, and writing.

Let a model compute averages or spot trends from raw rows and you get plausible fabrication. Enforce this by making the prompt contract carry no raw time-series at all.

**C3 — Free-text "how I feel" is not analysable.**

Structured Likert scales (fixed dimensions, 1–5) as the primary capture, with free text as an optional secondary field. You need consistent, comparable numbers to correlate against.

**C4 — The biggest drivers of "why I feel rough" are not in your list.**

Sleep, HR and training load matter, but in most people the dominant day-to-day confounders are **alcohol, caffeine timing, meal timing, work stress, illness and travel**. Alcohol in particular wrecks sleep architecture and HRV, and will otherwise appear in your data as an unexplained bad night.

You have deferred quantified alcohol and caffeine tracking to post-beta (D6). That is a reasonable scope call, but be clear about the cost: **until those are logged, some fraction of your bad days will be genuinely unexplainable, and the system will correctly say so rather than inventing a reason.** The mitigation is cheap — keep the binary tags in the check-in from day one (§7.2). One tap, no extra screen, and it means when you do switch on the quantified fields you already have months of coarse history to compare against.

**C5 — Supplement *intake* tracking is low value; supplement *change* tracking is high value.**

Your stack is fixed and daily. Logging "took my vitamin D" 365 times tells you nothing, because there is no variance to correlate against. What tells you something is knowing exactly when you started, stopped, or changed a dose. Two tables, not one: a daily adherence checklist, plus a dated **protocol change log**. The change log is what makes before/after analysis possible and is the foundation of the experiment engine.

**C6 — Missing data must be a first-class concept.**

Given D3, this is not hypothetical — you will have nights without the watch. If the system treats missing HRV as zero, or invents an explanation for a day it cannot see, it destroys its own credibility. Every derived metric carries `confidence` and `completeness`, and the brief states plainly when it is reasoning with gaps.

### 2.3 What to add

| Addition | Rationale |
|---|---|
| **Readiness score with visible component breakdown** | A glanceable number that is never a black box — always shows "62, driven by −18 sleep debt, −9 elevated RHR". Transparency is what stops it becoming another meaningless ring to close. |
| **N-of-1 experiment engine** | The only honest way to answer "does magnesium actually help my sleep". Turns the dashboard from descriptive to investigative. |
| **Feedback on the brief itself** | One tap: useful / not useful / wrong. Without it you have no idea whether the AI layer earns its place. |
| **Data freshness panel** | Last successful sync per source. Silent ingestion failure is the most common way self-hosted dashboards rot. |
| **Weekly retrospective** | Sunday brief covering trends, adherence and training progression. Daily briefs are tactical; you need something strategic. |
| **Body composition trajectory** | Muscle gain and fat loss simultaneously needs weight trend (EWMA), protein in g/kg, and volume progression viewed together. Raw daily weight is noise. |
| **Manual override / annotation** | Mark a day "excluded" (illness, holiday) so outliers do not poison baselines. |

### 2.4 Explicitly not building

Social features. Multi-user support. Real-time streaming. Medical diagnosis of any kind (§12). Play Store distribution — the Android app is sideloaded for personal use.

---

## 3. Data sources — verified availability

Researched 3 September 2026. Re-verify at implementation time.

| Source | Access method | Automated? | Confidence |
|---|---|---|---|
| **Hevy** | Public REST API, `api-key` header — **Pro owned** | Yes, day one | High |
| **Withings scale** | Public Health Data API, OAuth2, free tier | Yes, day one | High |
| **Samsung Health / Health Connect** | On-device Android API — needs the companion app (§3.3) | Phase 3 | High |
| **MyFitnessPal** | Calories via Health Connect; macros only via Premium CSV | Partial | Medium |
| **Subjective check-in** | Your own form | N/A | N/A |

### 3.1 Hevy — the easy one

```
GET  /v1/workouts                        # paginated, max pageSize 10
GET  /v1/workouts/events?since=<ISO>     # incremental sync — use this
GET  /v1/workouts/count
GET  /v1/workouts/{id}
GET  /v1/exercise_history/{templateId}
GET  /v1/body_measurements
Auth: header  api-key: <uuid>
```

- Backfill once via `/v1/workouts` paging, then go incremental on `/v1/workouts/events?since=`.
- Page size caps at 10 for workouts, so a deep backfill is many sequential requests. Fine as a one-off; add a small delay and back off on 429.
- No documented rate limit. Be conservative.
- Key is generated at `hevy.com/settings?developer` and is tied to your account.

### 3.2 Withings — better than routing through Health Connect

Your scale already syncs to Health Connect, but going direct is the better call: the Withings Public API has a **free tier supporting up to 5,000 active users at 120 requests per minute**. Direct means no dependency on the Health Connect chain, cleaner history, and it works from Phase 1 before the Android app exists.

- OAuth2 authorisation code flow; register a personal application in the Withings developer portal.
- Relevant endpoints: `Measure - Getmeas` for weight and body composition.
- Store the refresh token securely and handle rotation — Withings refresh tokens are single-use on some flows, so persist the new one on every refresh or you will silently lose access in a fortnight.
- Deep historical backfill available via date-ranged queries. Do it once at setup.

### 3.3 Samsung Health → your backend

**Health Connect is an on-device Android API. There is no cloud endpoint.** Data has to be pushed off the phone by something running on the phone.

**Primary route — the companion app (Phase 3).** `react-native-health-connect` is a maintained Android library that works with Expo via a config plugin and a development build. The app reads Health Connect on a background schedule and POSTs to your API.

**Fallback route — Health Sync → Google Drive CSV.** Health Sync (Play Store, small one-off cost) reads Samsung Health and Health Connect and writes scheduled CSV exports to Google Drive, which your backend polls via the Drive API. Keep this documented as a contingency; do not build it unless needed.

**Known risk — HRV and SpO2.** Samsung's documentation confirms activity, steps, exercise, heart rate and sleep synchronise to Health Connect. It does **not** confirm HRV, SpO2 or body composition. **Verify empirically in Phase 3 before the readiness score depends on HRV.** The fallback readiness formula (§6.3) uses sleep and resting HR only.

**Watch8 Classic specifics (D3).** Samsung's guidance is that the watch must be worn to bed for at least 3–4 hours a night, on at least 3 of any 14 days, to activate sleep tracking and Vascular Load.

This makes S6 a hard requirement: **wear the watch overnight at least 5 nights a week for the 6-week baseline.** Sporadic wear does not merely reduce data volume, it corrupts baselines — if you only wear it on nights you sleep well, your baseline is biased and every deviation calculated against it is wrong.

### 3.4 MyFitnessPal — the weak link

| Data | Route | Automated? |
|---|---|---|
| Calories eaten | Written to Health Connect as a **meal summary, not individual foods** | Yes (Phase 3) |
| Water | Written to Health Connect, one-way | Yes (Phase 3) |
| Cardio exercise | Written to Health Connect | Yes |
| **Protein, carbs, fat, fibre, micronutrients** | **Not written to Health Connect.** CSV export only, **Premium-gated**, emailed zip | **No** |

Three options, in order of preference:

1. **Switch to MacroFactor or Cronometer.** Both offer free, unrestricted data export. This is the cleanest answer, and the migration cost is a few days of parallel logging.
2. **Stay on MFP, accept a monthly manual macro import.** Workable, but you will forget, and monthly granularity is too coarse for daily protein feedback.
3. **Stay on MFP, calories only.** Simplest. Loses protein tracking, which materially weakens the body-composition half of the system.

**Recommendation: option 1.** Decide before Phase 3 — nothing earlier depends on it.

### 3.5 Backfill plan (D9)

| Source | Method | Expected depth |
|---|---|---|
| Hevy | API paging, one-off script | Full account history |
| Withings | Date-ranged API queries | Full account history |
| Samsung Health | **One-off manual export** from the Samsung Health app, parsed into `raw_records` | Potentially years |
| MyFitnessPal | One-off Premium CSV export (if pursued) | Full history |
| Subjective | None — starts from day one | n/a |

Run the Samsung Health manual export in Phase 0, before anything else. It costs ten minutes, and the parsed history is what lets your baselines be meaningful from week one rather than week six.

---

## 4. Architecture

### 4.1 Overview

```
Galaxy Watch8 ─┐  Withings ─┐  Hevy (cloud) ─┐  MyFitnessPal ─┐
               │            │                │                │
   PHONE: Samsung Health ──► Health Connect ◄─────────────────┘
          Companion app reads HC on schedule (Phase 3)
               │ HTTPS POST  │ OAuth2 pull   │ api-key pull
               ▼             ▼               ▼
   INGESTION LAYER — one adapter per source
   normalise → validate → idempotent upsert → raw_records retained
               ▼
   POSTGRES — canonical schema (§5)
               ▼
   METRICS ENGINE (deterministic, unit-tested)
   baselines · deviations · sleep debt · load · readiness · completeness
        ▼                              ▼
   FASTAPI (API-first)  ◄──►  AI LAYER (Claude API)
        ▼
   ONE EXPO CODEBASE
     ├─ Web (React Native Web) → PWA, live Phase 1
     └─ Android (EAS build, sideloaded) → Phase 3
         + react-native-health-connect  → replaces the CSV bridge
         + expo-notifications           → replaces email delivery
```

### 4.2 The key architectural decision: one codebase

**The native Android app you want as a UI is also the only clean way to read Health Connect.** Build two separate things and you build the frontend twice and still need the CSV bridge in the interim.

**Recommendation: Expo (React Native + React Native Web) from day one.**

The honest trade-off is charting. React Native charting libraries are meaningfully behind Recharts, and this is a chart-heavy application. Two mitigations: keep the Today screen simple (it is tiles and text, not charts), and if the Trends screen proves frustrating, render its charts as a lightweight web view served by the backend.

### 4.3 Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | **FastAPI** (Python 3.12), API-first | Strong typing, auto OpenAPI docs, trivial to write jobs against. |
| DB | **Supabase Postgres** (free tier) | Free tier ample for one user. |
| Migrations | **Alembic** | Schema will change constantly. Never hand-edit tables. |
| Frontend | **Expo SDK + TypeScript + Expo Router** | One codebase, web now, Android later. |
| Styling | **NativeWind** | Tailwind syntax across both targets. |
| Charts | **victory-native** or **react-native-gifted-charts** | Web-view escape hatch if needed. |
| Health Connect | **react-native-health-connect** + Expo config plugin | Phase 3. Android only. |
| Hosting — API | **Fly.io** or **Railway** free/hobby tier | Verify current tiers. |
| Hosting — web | **Vercel** or **EAS Hosting**, free tier | No custom domain (D10). |
| App distribution | **EAS Build → APK, sideloaded** | No Play Store, no developer fee. |
| Scheduling | **GitHub Actions** cron | Free, adequate for daily jobs. |
| LLM | **Claude API**, Sonnet tier, structured JSON output | ~2 calls/day. |
| Email | **Resend** free tier | Delivery for v1 (§11). |
| Auth | Supabase Auth, single account, magic link | Do not build user management. |
| Monitoring | **Healthchecks.io** dead-man's switch | Catches silent sync failure. |

### 4.4 Running cost (D4)

Supabase free, Vercel free, GitHub Actions free, Resend free, Healthchecks free, Withings API free, Fly.io free-to-low hobby tier, Hevy Pro already owned. The only variable cost is the Claude API at ~2 calls/day. **Verify all current tiers at implementation time.**

### 4.5 Rejected alternatives

- **Home Assistant + Grafana** — good dashboards, poor fit for a bespoke AI reasoning layer and custom data model.
- **Make.com + Google Sheets** — fastest to something, but hits a hard ceiling on correlation analysis within weeks.
- **Self-hosting on the RTX 5080 box** — only up when the PC is on, and you want this on your phone at 07:00. Local LLM inference remains an interesting Phase 6 privacy option.
- **Play Store distribution** — pointless for a single-user app.

---

## 5. Data model

### 5.1 Principles

- **Store raw, compute derived.** Never overwrite a raw record with a calculated value.
- **Idempotent upserts** keyed on `(source, source_record_id)`.
- **Timezone-aware throughout.** Store UTC, render Europe/London. Define "sleep for day D" as the session *ending* on day D, and unit-test it — including the BST/GMT transitions.
- **A `days` row is the join key.** One row per calendar date.

### 5.2 Tables

```sql
sync_runs(id, source, started_at, finished_at, status, records_ingested, error_message)

raw_records(id, source, source_record_id, record_type, payload jsonb, ingested_at,
            UNIQUE(source, source_record_id))

days(date PRIMARY KEY, is_excluded bool, exclusion_reason text, notes text)

sleep_sessions(id, date, start_at, end_at, duration_min, time_in_bed_min,
               efficiency_pct, deep_min, rem_min, light_min, awake_min,
               avg_hr, min_hr, avg_hrv_ms, avg_spo2, respiratory_rate,
               source, confidence)

heart_metrics(date, resting_hr, avg_hr, max_hr, hrv_rmssd_ms, vo2max,
              stress_avg, energy_score, source)

activity_daily(date, steps, distance_m, active_energy_kcal, total_energy_kcal,
               active_minutes, floors, source)

workouts(id, date, start_at, end_at, type, duration_min, source, source_record_id,
         title, notes, perceived_exertion_1_10, total_volume_kg, set_count,
         avg_hr, max_hr, energy_kcal)

workout_sets(id, workout_id, exercise_name, exercise_template_id, set_index,
             set_type, weight_kg, reps, rpe, distance_m, duration_sec, is_pr)

body_measurements(date, weight_kg, body_fat_pct, muscle_mass_kg, bone_mass_kg,
                  water_pct, waist_cm, chest_cm, arm_cm, thigh_cm, source)

nutrition_daily(date, calories_kcal, protein_g, carbs_g, fat_g, fibre_g,
                sodium_mg, water_ml, alcohol_units, caffeine_mg,
                last_caffeine_at, last_meal_at, source, completeness_pct)
-- macros may be NULL under MyFitnessPal (§3.4)

checkins(date PRIMARY KEY, submitted_at, submitted_late, energy_1_5, mood_1_5,
         sleep_quality_1_5, soreness_1_5, motivation_1_5, focus_1_5, stress_1_5,
         overall_1_10, tags text[], free_text)

supplements(id, name, dose_amount, dose_unit, form, schedule, is_active,
            notes, evidence_note)

supplement_log(date, supplement_id, taken, taken_at, dose_override,
               PRIMARY KEY(date, supplement_id))

protocol_changes(id, changed_at, entity_type, entity_id, change_type,
                 old_value, new_value, rationale, experiment_id)

daily_metrics(date PRIMARY KEY, computed_at, readiness_score,
              readiness_components jsonb, readiness_confidence,
              sleep_debt_14d_min, sleep_midpoint_variance_min,
              rhr_deviation_bpm, hrv_deviation_pct,
              acute_load_7d, chronic_load_28d, acwr,
              weight_ewma_kg, weight_trend_kg_per_week,
              protein_g_per_kg, data_completeness_pct)

briefs(id, date, type, model, prompt_version, phase, input_snapshot jsonb,
       output jsonb, generated_at, delivered_via, feedback_rating, feedback_note)

experiments(id, hypothesis, metric, intervention, baseline_start, baseline_end,
            intervention_start, intervention_end, status, result_summary,
            effect_size, confidence_note)

insights(id, discovered_at, statement, supporting_metric, sample_size,
         strength, status)

devices(id, platform, push_token, last_seen_at)
```

---

## 6. Metrics engine

Pure functions over the database. No LLM involvement. Every one unit-tested against fixtures.

### 6.1 Baselines

- Rolling 30-day **median** for RHR, HRV, sleep duration, sleep efficiency.
- Excluded days never enter a baseline.
- A baseline requires ≥ 14 observations before it is reported; below that, "establishing baseline".
- **Wear-bias guard (D3):** if overnight wear falls below 4 nights in any rolling 7, flag the sleep baseline as `potentially_biased`. A baseline built only from nights you chose to wear the watch is not a baseline.

### 6.2 Derived metrics

| Metric | Definition | Notes |
|---|---|---|
| **Sleep debt (14d)** | Σ(target − actual) over 14 days, floored at 0 per night | Target configurable, default 7h30 |
| **Sleep midpoint variance** | SD of sleep midpoint over 14 days | Circadian regularity — strong and underrated predictor |
| **RHR deviation** | today − 30d median | > +5 bpm is meaningful |
| **HRV deviation** | (today − 30d median) / 30d median | Only if HRV proves available (§3.3) |
| **Session load** | duration_min × RPE, or volume-load for strength | Simple, robust, no HR dependency |
| **Acute load** | 7-day rolling sum of session load | |
| **Chronic load** | 28-day rolling average of weekly load | |
| **ACWR** | acute ÷ chronic | > 1.5 flags a spike. A heuristic — treat as a prompt to look, not a verdict. |
| **Weight EWMA** | α = 0.1 | Never show raw daily weight as a trend |
| **Weight trend** | slope of EWMA over 14 days, kg/week | |
| **Protein g/kg** | protein_g ÷ weight_ewma_kg | Target ~1.6–2.2 g/kg. **NULL under MyFitnessPal** |
| **Volume progression** | Per-exercise 4-week volume-load slope | Is progressive overload actually happening |
| **Data completeness** | % of expected fields present for the day | Drives brief confidence |

### 6.3 Readiness score

A 0–100 composite, **always shown with its component breakdown**.

```
readiness = 100
          + w1 · sleep_duration_z
          + w2 · sleep_efficiency_z
          + w3 · (−rhr_deviation_z)
          + w4 · hrv_deviation_z            [if HRV available]
          + w5 · (−sleep_debt_normalised)
          + w6 · (−acwr_penalty)
          + w7 · subjective_yesterday_z
```

- Weights live in config, not code.
- If HRV is unavailable, redistribute w4 across w1–w3 and set `readiness_confidence = reduced`.
- If completeness < 60%, emit no score — emit `insufficient_data`.
- Store `readiness_components` as JSON so the brief can name the top two contributors verbatim.

**Fallback formula** (no HRV): sleep duration, sleep efficiency, RHR deviation, sleep debt, subjective.

---

## 7. Subjective check-in

### 7.1 Constraints

- **Under 30 seconds.** Hard requirement.
- One screen, no scrolling on a phone.
- Same time daily — within 30 minutes of waking.
- Missing a day must never break anything downstream.
- Only `overall_1_10` is required; a partial submission beats none.

### 7.2 Fields

**Core sliders (1–5):** `energy` · `mood` · `sleep_quality` · `soreness` · `motivation` · `focus` · `stress`

**Headline:** `overall_1_10`

**Confounder tags (multi-select chips) — included from day one despite D6:**
`alcohol` · `late_meal` · `late_caffeine` · `poor_sleep_env` · `work_stress` · `travel` · `illness` · `hangover` · `late_screen` · `dehydrated` · `no_watch` · `headache` · `sore_throat`

`no_watch` is worth its place on its own — it distinguishes "did not sleep well" from "did not measure".

**Deferred to post-beta (D6):** `alcohol_units`, `last_caffeine_time`. Schema columns exist now and sit NULL.

### 7.3 Anti-friction measures

- Deep link from the morning notification straight into the form.
- Pre-fill with yesterday's values.
- Streak counter.
- Backfill allowed up to 3 days, flagged `submitted_late`.

---

## 8. Supplements and protocol changes

### 8.1 Current stack (seed data)

| Supplement | Dose | Schedule |
|---|---|---|
| Fish oil | 4 softgels | Daily |
| Multivitamin | 2 tablets | Daily |
| Vitamin C | 1,000 mg | Daily |
| Vitamin D3 | 4,000 IU (100 µg) | Daily |
| Creatine | ~6 g (2 scoops) | Daily |
| Magnesium complex | 420 mg elemental (2 caps) | Bedtime |
| BCAA | 2 tablets pre + 2 post | Workout days |
| Beta-alanine | 1,500 mg (2 caps) | Pre-workout |

### 8.2 Daily adherence

A checklist rendering only what is scheduled that day. Two taps: "all taken", or individual toggles. Produces streaks and, more usefully, gap detection.

### 8.3 Protocol change log — the important half

Every start, stop, dose change or timing change gets a dated row with a rationale. Each change automatically:

1. Draws a vertical annotation on all relevant charts.
2. Opens a 14-day watch window the metrics engine tracks.
3. Queues a before/after comparison for the AI to narrate when the window closes.

### 8.4 N-of-1 experiments

- **Hypothesis** — "Magnesium at bedtime improves my sleep efficiency."
- **Primary metric** — one, chosen before starting.
- **Design** — ideally A-B-A. Minimum 14 days per block.
- **Blinding** — usually impossible; record that as a stated limitation.
- **Analysis** — mean difference plus a bootstrap confidence interval, computed in code. Be blunt when the interval crosses zero.
- **Output** — written to `experiments` and, if convincing, promoted to `insights`.

The AI **proposes** experiments and **narrates** results. It never computes them.

---

## 9. AI layer

### 9.1 Daily brief

Generated ~06:30, delivered by email (Phase 2) then push (Phase 3), readable in 60 seconds.

**Input contract.** Compact JSON only. **No raw time-series.**

```json
{
  "date": "2026-09-04",
  "phase": "baseline",
  "data_completeness_pct": 87,
  "readiness": { "score": 62, "confidence": "reduced",
                 "top_contributors": [
                   {"factor": "sleep_debt_14d", "impact": -18},
                   {"factor": "rhr_deviation",  "impact": -9}] },
  "sleep": { "duration_min": 342, "baseline_min": 430, "efficiency_pct": 81,
             "deep_min": 48, "rem_min": 62, "debt_14d_min": 265,
             "midpoint_variance_min": 74, "baseline_bias_flag": false },
  "cardio": { "resting_hr": 58, "baseline_rhr": 52, "hrv_ms": null },
  "training": { "yesterday": {"type":"strength","title":"Push A",
                              "volume_kg": 9840, "rpe": 8},
                "acute_load_7d": 2140, "chronic_load_28d": 1680, "acwr": 1.27,
                "days_since_rest": 4 },
  "nutrition": { "calories": 2180, "protein_g": null,
                 "protein_g_per_kg": null, "completeness_pct": 45 },
  "body": { "weight_ewma_kg": 84.2, "trend_kg_per_week": -0.24 },
  "subjective_yesterday": { "overall": 6, "energy": 3, "stress": 4,
                            "tags": ["work_stress","late_screen"] },
  "supplements": { "adherence_7d_pct": 93, "missed_yesterday": ["magnesium"] },
  "active_experiments": [],
  "recent_protocol_changes": [],
  "known_insights": []
}
```

**Output contract.** Structured JSON, rendered by the frontend.

```json
{
  "headline": "One sentence. The single most important thing today.",
  "status": "green | amber | red",
  "why": [{"observation": "…", "evidence": "…", "confidence": "high|medium|low"}],
  "do_today": [{"action": "…", "rationale": "…", "priority": 1}],
  "avoid_today": ["…"],
  "watch_items": ["…"],
  "training_recommendation": {
    "verdict": "train_hard | train_light | active_recovery | rest",
    "rationale": "…"
  },
  "supplement_note": "… or null",
  "data_caveats": ["Protein unavailable — MyFitnessPal does not sync macros"],
  "proposed_experiment": null
}
```

### 9.2 Hard rules for the prompt

Written into the system prompt and regression-tested against the eval set:

1. **Never state a number not present in the input JSON.** No arithmetic, no derivation, no imputation of nulls.
2. **Respect `phase`.** In `baseline`, causal language is forbidden. In `associative`, every causal claim carries a sample size and a hedge. Only in `experimental`, and only for a completed experiment, may a claim be stated as established.
3. **Name the caveat when data is missing.** Never explain a day you cannot see. A null is a null, not a zero.
4. **Maximum three `do_today` items.**
5. **No medical advice, diagnosis or dosing instruction.** See §12.
6. **Prefer "I don't know" to a plausible story.** Explicitly rewarded in the prompt.
7. **No motivational filler.** Direct, factual register.

### 9.3 Other AI surfaces

- **Weekly retrospective** (Sunday evening) — trends, adherence, training progression, one focus for the week, one candidate experiment.
- **Experiment result narration** — plain-English write-up of a computed result, including honest reporting of nulls.
- **Ad-hoc chat over your data** (Phase 6) — question answering against the metrics engine via tool calls, never over raw rows.

### 9.4 Prompt versioning and evaluation

- Every brief stores `prompt_version`, `phase` and the full `input_snapshot`, so any past day can be re-run against a new prompt and diffed.
- Maintain an eval set of ~15 hand-picked days: a great day, a terrible day, a no-watch day, a missing-macros day, an overtrained day, a post-illness day. Re-run on every prompt change.
- `feedback_rating` is the ground-truth signal. Review monthly.

---

## 10. UI

### 10.1 Screens

**1. Today** *(default)* — readiness ring with its two top contributors named beneath; the daily brief rendered from its JSON with one-tap feedback; check-in prompt if not yet submitted; supplement checklist; four tiles (sleep, resting HR, yesterday's training, weight trend).

**2. Trends** — selectable metric, 7/30/90/365-day ranges, baseline band behind the series, protocol changes as vertical annotations, subjective `overall` overlaid on any objective metric.

**3. Training** — volume by muscle group, per-exercise progression with PR markers, acute vs chronic load with ACWR.

**4. Body** — weight EWMA vs raw scatter, body composition from Withings, protein g/kg against target.

**5. Supplements** — current stack, adherence heatmap, change history timeline.

**6. Experiments** — active and completed, with result summaries.

**7. Data health** — last sync per source, completeness by day, ingestion errors, **overnight wear rate**.

### 10.2 Principles

- **Mobile-first.**
- **Glanceable in 5 seconds, explorable in 5 minutes.**
- Dark mode by default.
- Every number tappable to reveal its definition and inputs. No black boxes.
- Missing data rendered explicitly as a gap. Never interpolated silently.

### 10.3 Design language — "Glacier"

Locked. The reference implementation is `docs/ui/glacier-today.html` — the Today
screen in both themes, rendered from the §9.1 example payload. The Expo app
implements these tokens. Nothing below is decoration: five of the rules in
§10.3.5 exist to make the invariants in §5.1, §9.2 and §12 *visible* rather than
merely true.

**Intent.** Apple's spacing and restraint, dark-first, with an instrument-panel
voice carried by monospaced micro-labels. Glanceable at 06:30 and honest about
what it cannot see.

#### 10.3.1 Colour

Two themes, both designed — light is not an inversion of dark. Components read
tokens, never literals, so a colour is never defined in only one theme.

| Token | Dark | Light | Use |
|---|---|---|---|
| `bg` | `#080B10` | `#EEF1F5` | page ground, beneath two accent veils |
| `surface` | `rgba(255,255,255,.045)` | `rgba(255,255,255,.74)` | glass card fill |
| `surface-2` | `rgba(255,255,255,.075)` | `rgba(255,255,255,.94)` | inset blocks, chart tracks |
| `hairline` | `rgba(255,255,255,.10)` | `rgba(12,22,32,.11)` | 1px borders and rules |
| `hairline-2` | `rgba(255,255,255,.20)` | `rgba(12,22,32,.22)` | dashed gap outlines, emphasis |
| `ink` | `#EAF0F6` | `#0D141B` | primary text and figures |
| `ink-2` | `#9BA9B8` | `#4B5866` | secondary text |
| `ink-3` | `#68747F` | `#7B8794` | micro-labels, axis text |
| `accent` | `#5FD0E6` | `#0E8CA8` | charts, controls, anything touchable |
| `accent-soft` | `rgba(95,208,230,.16)` | `rgba(14,140,168,.13)` | area fills, selected chips |
| `on-accent` | `#04161C` | `#FFFFFF` | text on an accent fill |
| `good` | `#7CC46A` | `#3F8F3A` | status green |
| `warn` | `#E9A94A` | `#9E6B14` | status amber |
| `crit` | `#EE6C63` | `#C24A40` | status red, negative contributors |

The ground carries two low-opacity radial veils — glacier cyan top-left, a cool
iris top-right — fixed to the viewport. They are the only gradients in the
system.

**Glacier cyan is the interface; green, amber and red are the status palette.**
The accent is never used to mean "good", and a status colour is never used for
decoration or for a chart series. This is what makes an amber ring legible as
amber rather than as styling.

Source provenance uses its own muted dots, never the status or accent hues:
Samsung Health `#5B93D6`, Hevy `#D9803F`, Withings `#4FB3C4`, MyFitnessPal
`#8AA83F`.

#### 10.3.2 Type

| Role | Face | Treatment |
|---|---|---|
| Figures and headlines | **Sora** 500/600/700 | `tabular-nums`, tight tracking (−0.02em, −0.04em on large figures) |
| Body and UI | **Manrope** 400–700 | 15px base, 1.5 line height, ~65ch measure |
| Micro-labels, evidence, units | **JetBrains Mono** 400–600 | 10px, 0.14em tracking, uppercase for labels |

The mono is load-bearing, not stylistic: it carries the raw numbers under every
AI claim ("342 MIN · BASELINE 430 MIN"), which is what keeps the narration
visibly standing on the metrics engine rather than replacing it. On native, San
Francisco may substitute for Manrope; Sora and JetBrains Mono ship with the app.

#### 10.3.3 Materials and layout

- **Glass.** `surface` over the veiled ground, `saturate(150%) blur(20px)`, a 1px
  `hairline` border, one soft shadow. No inner glows, no gradient borders.
- **Radii** 10 / 16 / 22 px — controls, inset blocks, cards.
- **Not everything is a card.** Inside a card, separate with hairline rules and
  spacing. Nested cards are not used. A *dashed* container means one thing only:
  missing data.
- **Grid.** 12 columns, 14px gutter, 1180px max. One column below 1000px; tiles
  go full width below 560px.
- **Mobile is the primary composition.** Today is a single scrolling column:
  readiness → brief → check-in (only while outstanding) → four tiles →
  supplements → not measured.

#### 10.3.4 Components

- **Readiness gauge.** 270° arc, gap at the bottom, 13px stroke, round caps,
  ends labelled 0 and 100. Painted in the **status** colour. Score in Sora 60px
  over "of 100". Beneath: the status word, the confidence sentence whenever
  `readiness_confidence = reduced`, then the top two `readiness_components` as
  name, signed impact, and a bar scaled to the largest contributor.
  `insufficient_data` renders as the empty dashed arc with an em-dash — never a
  zero, never a placeholder score.
- **Brief.** Headline in Sora, ≤ 30ch. Each `why` is a hairline rule, the
  observation, its confidence chip, and its evidence line in mono. `do_today`
  is numbered because priority is ordered. `training_recommendation` sits in a
  filled block; `data_caveats` behind an amber rule. One-tap Yes/No writes
  `feedback_rating` (§9.4).
- **Metric tile.** Micro-label and signed delta on one line; the figure in Sora
  with its unit in body weight; a micro-chart; a foot carrying the source chip
  and the comparison basis ("median 52", "EWMA · 30 d").
- **Micro-charts.** 2px lines, one emphasised endpoint dot, baseline as a shaded
  band or dashed rule, axis labels only at values the chart actually reaches.
  No gridlines and no legends — a single series is named by its tile.
- **Gaps.** A missing day inside a series is a hatched, dashed, full-height
  column. An unavailable metric is a dashed container holding an em-dash and the
  reason ("MyFitnessPal does not sync macros. Open item O2.").
- **Chips.** Source chips (5px dot + mono caps), confidence chips, and
  confounder tags as pills that fill with `accent-soft` when selected.
- **Phase pill.** Permanent in the top bar beside data completeness:
  `BASELINE · DAY 12 OF 42`. Its wording changes by phase; it never disappears.

#### 10.3.5 The five rules the UI enforces

1. **A gap is drawn as a gap.** Never a zero, never an interpolation, never a
   smoothed line across a missing night (§5.1).
2. **The phase is always on screen.** The pill is why the brief states
   deviations and claims no causes (§9.2).
3. **Status colour never travels alone.** Green, amber and red cannot be
   separated by colour alone under deuteranopia or protanopia, so every status
   carries its word and a glyph.
4. **No number is a black box.** Tap any figure for its definition, inputs,
   source and last sync (§10.2).
5. **Confidence sits with the claim,** not in a footnote — the chip is on the
   `why` line it qualifies.

#### 10.3.6 Motion and accessibility

- One orchestrated load: the arc sweeps and the score counts up over ~1.1s,
  cubic ease-out. Everything else is a 120–150ms state change.
  `prefers-reduced-motion` disables all of it.
- Body ink ≥ 4.5:1 contrast; micro-labels ≥ 3:1 and never the sole carrier of
  meaning.
- Hit targets ≥ 44px on native. Every interactive element has a visible focus
  state.
- Chart text and marks take the same tokens as the surface behind them, so both
  themes remain legible without a second palette.

The remaining six screens (§10.1) inherit these tokens; their compositions are
not designed yet. Phase 3 builds the language into the Expo app.

---

## 11. Delivery

**Phase 2 — Email.** Resend or equivalent, free tier. The brief renders as HTML with a deep link into the check-in.

**Phase 3 — Native push.** `expo-notifications` delivers the brief at 06:30 with a one-tap deep link to the check-in.

**WhatsApp — recommended against.** The cost is irrelevant at one message a day; the problem is setup (Meta Business account, dedicated phone number, template approval) to deliver a message to yourself. Revisit only if email proves too easy to ignore.

---

## 12. Safety and boundaries

Non-negotiable, and written into the system prompt:

1. **Not a medical device. Gives no medical advice.**
2. **No dosing instructions.** "The evidence for magnesium and sleep is mixed and worth testing" is permitted. "Increase to 600 mg" is not.
3. **No drug or supplement interaction advice.** Directs to a pharmacist or GP.
4. **Escalation triggers.** Sustained abnormalities — resting HR elevated > 10 bpm for 5+ consecutive days, unexplained weight loss, persistently very low subjective scores — produce a plain statement that this warrants a GP conversation, and no attempt to explain it.
5. **No intake or weight targets that trend toward restriction.** Hard floors on any suggested intake; never encourage a deeper deficit when weight trend is already negative and subjective energy is low.
6. **Confidence always stated.**

---

## 13. Privacy and security (D10)

- Single-user auth, magic link. **No public registration endpoint.**
- No custom domain; platform-provided subdomain.
- TLS everywhere, HSTS.
- Encryption at rest — verify your Postgres provider offers it.
- API keys and OAuth tokens in the platform secret store, never in the repo. Pre-commit secret scanner.
- No third-party analytics, no session recording, no ad SDKs.
- Only the compact summary JSON goes to the Claude API, never full history.
- Full JSON export endpoint.
- **Private** GitHub repository.
- Automated daily database backup with a **tested** restore.
- The sideloaded APK is signed with your own key and never distributed.

---

## 14. Roadmap

Each phase has an acceptance test. Do not start the next until the current one passes.

### Phase 0 — Setup
- **Run the Samsung Health manual export now** and keep the file.
- Obtain: Hevy API key, Withings developer app + OAuth credentials, Supabase project, Fly.io/Vercel accounts, Claude API key, Resend key.
- Repo skeleton (private), Alembic migrations, CI running tests, Healthchecks.io dead-man's switch.
- Decide §3.4 — stay on MyFitnessPal or switch.
- **Accept when:** `alembic upgrade head` builds the full schema and a health-check endpoint returns 200 in production.

### Phase 1 — Core loop
- Schema implemented.
- **Hevy adapter** — full backfill, then incremental via `/workouts/events`.
- **Withings adapter** — OAuth flow, full backfill, daily pull.
- Check-in form in Expo web, including the confounder tags.
- Minimal Today screen.
- **Start wearing the watch overnight, 5+ nights a week.**
- **Accept when:** you complete a check-in 7 days running, and Hevy plus Withings history is fully and correctly imported.

### Phase 2 — The AI brief
- Metrics engine v1 — baselines, deviations, training load, weight EWMA.
- Daily brief per the §9 contracts, phase-locked to `baseline`.
- Email delivery at 06:30 with feedback capture.
- Supplement checklist seeded; protocol change log.
- **Accept when:** you receive an accurate brief 7 days running and every number in it traces back to the input JSON.

### Phase 3 — The app and Health Connect
- Expo dev build with `react-native-health-connect`; permissions flow; background sync POSTing to your API.
- EAS build → signed APK sideloaded.
- Parse and ingest the Phase 0 Samsung Health export.
- **Verify HRV and SpO2 availability** and finalise the readiness formula.
- MyFitnessPal calories via Health Connect.
- `expo-notifications` replaces email delivery.
- **Accept when:** sleep, resting HR and steps land automatically for 7 consecutive days with zero manual intervention, and the brief arrives as a push notification.

### Phase 4 — Full metrics and dashboard
- Readiness score with component breakdown and wear-bias guard.
- Trends, Training, Body and Data Health screens.
- Weekly retrospective.
- **Accept when:** you can answer "how has my sleep tracked against training volume over 90 days" in under 30 seconds on your phone.

### Phase 5 — Insight and experimentation
- Correlation analysis with proper significance handling and multiple-comparison awareness.
- Brief moves to `associative`.
- N-of-1 experiment engine; protocol change watch windows.
- Add quantified alcohol and caffeine capture (D6).
- **Accept when:** the system produces one insight you did not already know and it survives scrutiny.

### Phase 6 — Extensions
Chat over your own data. Predictive readiness. iOS target. Local LLM inference on the RTX 5080.

---

## 15. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **Check-in adherence collapses after the novelty** | High | Fatal | Sub-30-second design, pre-filled defaults, streaks, one-tap deep link. Below 60% over two weeks is a design failure requiring redesign, not more discipline. |
| R2 | **Overnight watch wear is inconsistent (D3)** | High | High | Wear-bias guard on baselines; `no_watch` tag; `insufficient_data` rather than a fabricated score. |
| R3 | Protein data unavailable on MyFitnessPal | High | Medium | Decide §3.4 before Phase 3; nulls propagate honestly to the brief's caveats |
| R4 | HRV/SpO2 unavailable via Health Connect | Medium | Medium | Verify in Phase 3; fallback readiness formula ready |
| R5 | AI produces confident nonsense and you stop trusting it | Medium | High | Phase-locked language, no-arithmetic rule, mandatory confidence, eval set |
| R6 | Silent ingestion failure | High | Medium | Dead-man's switch, Data Health screen, brief states its own completeness |
| R7 | Scope creep stalls the project before v1 ships | High | High | Phase gates with acceptance tests; nothing from a later phase starts early |
| R8 | RN charting frustration on the Trends screen | Medium | Low | Web-view escape hatch (§4.2) |
| R9 | Correlation mistaken for causation | High | Medium | Explicit phase model; experiments as the only route to causal claims |
| R10 | Withings refresh-token rotation silently breaks sync | Medium | Medium | Persist the new refresh token on every refresh; dead-man's switch catches it within a day |
| R11 | Health data exposure | Low | Severe | §13 in full |
| R12 | Timezone / sleep-boundary bugs corrupt joins | Medium | Medium | "Sleep belongs to the day it ends", unit-tested including BST/GMT transitions |
| R13 | Health Connect permissions prove restrictive | Low | Medium | Health Sync + Google Drive CSV documented as fallback (§3.3) |

---

## 16. Remaining open items

| # | Item | Needed by | Resolution |
|---|---|---|---|
| O1 | Expo one-codebase vs Next.js (§4.2) | Phase 1 | **Resolved 3 Sep 2026: Expo** |
| O2 | MyFitnessPal: stay, switch, or Premium monthly import (§3.4) | Phase 3 | **Provisionally: stay on MFP, calories only. Revisit.** |
| O3 | Sleep target for sleep-debt calculation | Phase 2 | **Resolved 3 Sep 2026: 7h30** |

---

## Appendix A — Verification notes

Researched 3 September 2026. Re-verify at implementation. Specifically unconfirmed and requiring empirical test:

- Whether HRV, SpO2 and body composition reach Health Connect from Samsung Health on the Watch8 Classic.
- Exactly which nutrition fields MyFitnessPal writes to Health Connect beyond calorie meal summaries and water.
- Current Hevy API rate limits (undocumented).
- Current free-tier limits for Supabase, Vercel, Fly.io, Resend and Healthchecks.
- Current Withings API plan terms.

## Appendix B — Sources

- [Hevy API OpenAPI specification](https://raw.githubusercontent.com/chrisdoc/hevy-mcp/main/openapi-spec.json)
- [Hevy API key setup and Pro requirement](https://docs.serval.com/sections/integrations/hevy)
- [Withings Public Health Data API — FAQ](https://developer.withings.com/developer-guide/v3/integration-guide/public-health-data-api/faq/)
- [Withings API plans — free tier limits](https://developer.withings.com/developer-guide/v3/withings-solutions/withings-api-plans)
- [Samsung — Health Connect FAQ, synced data types](https://developer.samsung.com/health/health-connect-faq.html)
- [Samsung — Health features on the Galaxy Watch8 and Watch8 Classic](https://www.samsung.com/uk/support/mobile-devices/health-features-on-the-galaxy-watch8-and-watch8-classic/)
- [Android — Health Connect comparison guide](https://developer.android.com/health-and-fitness/health-connect/comparison-guide)
- [react-native-health-connect](https://www.npmjs.com/package/react-native-health-connect)
- [MyFitnessPal — Health Connect FAQ and troubleshooting](https://support.myfitnesspal.com/hc/en-us/articles/10553948248973-Health-Connect-FAQ-and-Troubleshooting)
- [Health Sync — supported platforms and Google Drive CSV export](https://healthsync.app/about/)
