# Evaluation log

Every run is saved in `eval/results/` with the dataset hash, the rules hash,
the model and the prompt hash. Tuning happens on `*_tune.jsonl` only; the
test sets are run at the end of a stage and never used for tuning (SPEC 12.1).

All data is fictional or the public price list (CLAUDE.md, data tiers).

## A — match items

`match_tune.jsonl` (10 cases, 15 items, one with no catalog line): every
code confirmed by a domain expert.
`match_test.jsonl` (30 cases, 38 items, 6 with no catalog line), written
30.10.2026: 8 cases are job descriptions written by a domain expert
(`"source": "domain_expert"`), and the expert confirmed their codes.
Decisions from that review: acrylic paint has no catalog item (mx02: no
match); damp damage is a group of 8 items (mx05: any of them counts);
cross/barrel vaults and maykim in vaults have no catalog item (mx06: both
"no match"); anchors stay the two anchor items (mx08; a tension rod only as
an option to pick, never as a line). "Waste removal" alone means the
condition (included / not included), not the catalog item for others'
existing debris; our own waste charged apart is a priced line per
container or truck, with no catalog item. Seen during the review (search
only, no run on the set): the search for "תיקון נזקי רטיבות" did not
surface the damp items (the catalog says לחות / עלייה קפילרית); the fix
was checked on a new tuning case, not on mx05.

| Date | Run | Set | Top-1 | Top-3 | Recall@15 |
|---|---|---|---|---|---|
| 30.10 | search baseline, BM25 only | match_tune (14 items with a code) | 57.1% | 92.9% | 100% |
| 30.10 | search baseline, embeddings only | match_tune | 85.7% | 100% | 100% |
| 30.10 | search baseline, hybrid (RRF) | match_tune | 85.7% | 100% | 100% |
| 30.10 | search baseline, BM25 only | match_test (32 items with a code) | 59.4% | 78.1% | 87.5% |
| 30.10 | search baseline, embeddings only | match_test | 71.9% | 84.4% | 100% |
| 30.10 | search baseline, hybrid (RRF) | match_test | 65.6% | 78.1% | 100% |
| 2.11 | search baseline, hybrid, expert's damp words | match_tune (18 items with a code) | 88.9% | 100% | 100% |
| 2.11 | search baseline, hybrid, expert's damp words | match_test (31 items with a code) | 67.7% | 80.6% | 100% |

2.11.2026, damp words (`app/core/hebrew.py`, `_SYNONYMS`): a domain expert's
words for a damp problem (רטיבות, עובש, מלחים, "הקיר מתקלף") add the
catalog's words (לחות, עלייה קפילרית) to the keyword query; nothing is
removed. Checked on match_tune first (mt11, new: BM25 rank 4 -> 1, no
other row moved). On match_test the only row that moved is the damp row
(mx05: hybrid rank 12 -> 1); without the words the test set gives 64.5% /
77.4% / 100%.

On the test set the right line is always among the 15 candidates (hybrid),
so the choice is the Matcher's job (SPEC 12.2 decision rule). Hybrid is
below embeddings alone on Top-1 there; the search is not tuned on the test set.

### Agents (Intake + Matcher), tuning set only

"Found" = an expected item got a line with one of its codes. "Wrong" = a
suggested line whose code is no expected item's code.

| Date | Prompts | Found | Wrong lines | Notes |
|---|---|---|---|---|
| 30.10 | Intake v2, Matcher v2 | 78.6% (11/14) | 5 of 17 | split one job into steps; m² line for a job said in metres; cameras -> "communications technician" |
| 30.10 | Intake v3, Matcher v3 (+ quantity and unit) | 85.7% (12/14) | 1 of 13 | now merged two different jobs |
| 30.10 | Intake v3.1, Matcher v3.1 | **100% (14/14)** | 2 of 16 | one job split again (runs vary); cameras again |

2 model calls per request, 3–7 s. Answers vary between identical runs
(temperature 1.0 cannot be changed on this model), so the test set is run twice.

**Confidence (app/core/confidence.py), from the three runs above (45 lines):**
every correct line scored 0.80 or more; wrong lines from a weak search
scored 0.52–0.64. Review threshold set to 0.75: it flags those and no
correct line. A confident wrong line with a strong search score is not
caught by any threshold; the person approving the draft catches it.

### Agents on the test set — 2.11.2026, two runs (after the expert review)

`match_test.jsonl` (30 cases, 38 items: 31 with a code, 7 with none),
Intake v5 + Matcher v4.2, model gemini-3.5-flash-lite, confidence review
threshold 0.75. First agent run on this set.

| Run | Found | Wrong lines | Wrong lines marked for review | Seconds (median / max) |
|---|---|---|---|---|
| 1 | 71.0% (22/31) | 8 of 32 | 4 of 8 | 3.0 / 6.3 |
| 2 | 71.0% (22/31) | 8 of 30 | 5 of 8 | 3.0 / 5.7 |

Far below the tuning set (100%). Misses in both runs: "תיקוני טיח
ושליכט" got the plaster-renewal item (01.09.001.0060) instead of the
plaster-repair item (mx01, mx02; not marked for review); baseboards "מטר
אורך" (mx04); a shutter by its size (mx12, a size-sensitive pick, as
mt04/mt06 on tuning); maykim in vaults got a plaster item (mx06, marked);
others' debris left in the yard (mx20) came back with no line in both
runs. mx20 may come from the Matcher v4.2 sentence of 2.11 (below), or
not: there is no run of the old prompt on this set, and none is made now,
since choosing a prompt by the test set would tune on it. Not changed.
Items with no catalog line that still got one: mx27, mx30 (marked for
review) and the vaults/maykim of mx06. The damp row (mx05) was found in
run 1 and missed in run 2. Numbers for the video: these, as they are.

### Intake and Matcher prompt history

- **v2 (AI Studio, 29.10).**
- **v3 (30.10, tuning set):** Intake: steps of one action on one layer are one
  job ("remove the old paint and apply a new layer"); no quantity 1 when no
  number was said. Matcher: gets the stated quantity and unit, and picks a
  line whose unit and size fit them.
- **v3.1 (30.10, tuning set):** Intake: explicit examples of two jobs in one
  sentence (repair then paint; new sealing "including" peeling the old).
  Matcher: an hourly trade line (worker, technician) only for work hours,
  never for a job with no line of its own. Tuning stopped here, to avoid
  fitting 10 cases.
- **Matcher v4.2 (2.11, tuning set, after the expert review):** an item that names a
  special case ("of others", "already on site before the work") fits only
  a job that says the same case: our own waste per container is not the
  catalog's "others' existing debris" item (probe: "פינוי פסולת 2 מכולות"
  came back as that item, 2 m³). New tuning cases mt11 (damp words), mt12
  (former tenants' debris -> the item), mt13 (our waste per container ->
  no line); ap11 ("תוסיף פינוי פסולת" -> the waste condition), ap12
  (others' debris -> the new demo condition `existing_waste`). Six
  match_tune runs: mt13 no line in all six, mt12 found in five, mt11 a
  damp item in four. Code, same day: a said unit that is not the line's
  unit leaves the quantity empty (`check_line`), and "מכולה" / "משאית"
  count as said units, so 2 containers never become 2 m³.
- **Intake v5.1 (2.11, after the phone test; NOT MEASURED YET):** a
  request to add work is a job even about waste ("תוסיף פינוי פסולת",
  "פינוי פסולת 2 מכולות"); only a sentence on what the price includes is a
  condition ("add waste removal" must give a free priced line; our own
  waste is charged per container). Sets first: ap11
  relabelled (conditions: site_ready only), new mt14. Measure on
  match_tune and aplus_tune (two runs) on 3.11 (Gemini quota spent on 2.11).
  **Measured 3.11, two runs each (Matcher v4.2 unchanged):** the Intake
  part works — "פינוי פסולת" came back as a job in all four runs, never as
  a condition (ap11 conditions exact, site_ready only, both runs); ap09
  still `waste_excluded` (run 1 medium, unticked; run 2 high). But the
  **Matcher then picked the others'-debris item (01.24.040.0010) for the
  bare "פינוי פסולת" in 3 of 4 runs** (mt14 run 2, ap11 both; medium,
  needs review, quantity empty, so yellow and unticked in the app, not a
  red row). mt13 ("2 מכולות") stayed no line in both. match_tune: 94.7% /
  89.5% found, 2 / 4 wrong lines (2.11 with v4.2: 88.9% / 100%); the other
  misses are the known ones (mt04 railing height, mt10 cameras, mt11 damp
  in run 2). aplus_tune both runs: conditions recall 100%, precision 96%,
  ticked right 100%, payment 100%, no invented plan; ap06 (furniture ->
  site_ready, medium) as before.
- **Special-case item guard (3.11, code, user's choice over another prompt
  sentence):** rules.yaml `special_items` — the others'-debris item is kept
  only if the message says the case (`says_special_case`: one of the
  item's own words or plain words for old debris, with prefixes; no word
  taken from a test set). Otherwise the job is a red row (free line).
  Tuning set, two runs each: mt14 and ap11 no line in all four (was 3 of
  4 wrong), mt12 (former tenants' debris) still the item in both, mt13 no
  line. match_tune 94.7% / 100% found, 2 / 1 wrong lines (mt10 cameras
  both, mt11 damp in run 1, both known). aplus_tune: payment 100%, no
  invented plan, ticked right 100%; run 1 conditions recall 95.8% /
  precision 92%: ap09 "על חשבון המזמין" -> `existing_waste` (medium, not
  ticked) instead of `waste_excluded`, a condition pick the guard does not
  touch (run-to-run; right in the other three runs today). Not tuned.
- **Masked amount labels (3.11, live check, code):** `[סכום1]` was read
  as a said 1, so "מצלמות אבטחה" with no number kept the model's quantity
  1. `stated_quantities` now drops the labels first (also for the payment
  guard).
- **v5 (31.10, A+ payment):** Intake also returns the payment stages,
  each as `kind` (percent / amount / remainder) + `value`; the payment
  sentence still goes to the conditions too. See A+ below.
- **v4 (31.10, A+):** Intake also returns the condition sentences apart
  from the work ("the price does not include scaffolding" is not a job);
  the Matcher picks a library condition for each in the same call (see A+
  below). Regression check on match_tune, two runs: 85.7% (mt04 railing
  height, mt06 window area: size-sensitive picks) and 100%. The one run of
  v3.1 was 100%, so the drop is run-to-run variation (temperature is not
  sent; the model's default is 1.0), not the prompt. Wrong lines: mt10
  (security cameras), as before.

## A+ — proposal from a message (conditions and payment)

All A+ runs below used the 14-condition demo library; `site_ready` was
added on 31.10.2026 after them (no set sentence is about site readiness).

Sets (written 31.10.2026, before the prompts): `aplus_tune.jsonl` (10) and
`aplus_test.jsonl` (20). Each case is one message as the server gets it
(amounts already masked, `[סכום1]`), the condition keys, the condition
sentences with no library condition, and the payment stages (each stage is
one of: percent, amount label, remainder). Every demo condition appears in
both sets; there are cases with no condition, with "אין תנאים מיוחדים", and
with a condition the library does not have or says the opposite of. Rule
(31.10.2026): when payment stages are said, the general payment
condition is expected too. Labels are the developer's.

### Baseline: keywords (`eval/condition_keywords.py`)

Keywords are words of the library wording itself, no synonyms (a first
version had synonyms picked while looking at the sets and scored 100% /
92%; dropped as leaked).

| Set | Recall | Precision | Exact cases |
|---|---|---|---|
| tune | 75.0% | 93.8% | 40% |
| test | 78.8% | 86.7% | 65% |

Keywords cannot find a condition the library lacks, and cannot see "at the
client's expense" as the opposite of "included".

### Agents (Intake v4 + Matcher v4), tuning set only

One Matcher call picks lines and conditions together (2 calls a request).
Confidence: high 0.9, medium 0.6, low 0.3; the app ticks in advance only
above 0.75, i.e. "high".

| Run | Recall | Precision | Ticked correct | Not-in-library found | Seconds |
|---|---|---|---|---|---|
| v4 (31.10) | 100% | 90.9% | 100% | 0/2 | 3–6 |
| v4.1 + "low" = not in library (31.10) | 100% | 95.2% | 100% | 1/2 | 3–5 |

- v4: the payment condition always came back "medium" (not ticked), and
  both not-in-library sentences got the nearest condition (low/medium).
- v4.1: the prompt says not to fall back on the nearest condition and that
  payment is always "high"; code treats a "low" pick as not in the library.
  Left: "the client moves the furniture" → access, medium (shown, not
  ticked). Tuning stopped here; the test set runs at the end of A+, with
  payment, twice.

### Payment stages (Intake v5)

Compared per case: the same stages in the same order (percent to one
decimal, amount label, remainder), not the descriptions. Some cases accept
a second reading (`payment_also`: "one payment at the end" = 100% or the
remainder).

**Baseline: a regex** (`eval/payment_regex.py`): a number with "%", a
label, "יתרה"/"השאר", in order. Written before the natural set.

| Set | Regex | Agents |
|---|---|---|
| tune (10) | 100% | 90% (v5 kind + value) |
| test (20) | 100% | not run yet |
| natural (10) | 0% | 90% (all 9 cases with a plan right) |

- **tune/test are too regular for payment:** every stage was written with
  "%", a label or "יתרה", so the regex reads them all. Found 31.10.2026;
  the sets were not changed after that (the baseline had already run on
  the test set).
- **`aplus_natural.jsonl` (10, written 31.10.2026 before either method
  ran on it):** "שלושים אחוז", "חצי ... וחצי", thirds, "רבע", "40 אחוז",
  "תשלום אחד בסיום", "30 יום" (not a percent), "80 מ"ר, 3 קומות". Regex
  0/10, and it invented a plan for "the rest in two equal payments";
  agents 9/10. Decision (31.10.2026): payment stays with the AI.
- **The miss (pn08):** "מקדמה [סכום1], ואת השאר בשני תשלומים שווים" came
  back as label + 50% + remainder; the right answer is no plan (the stages
  cannot say "half of the rest"). The user sees it on the approval screen.
- **Intake v5, first form:** three optional fields (percent, amount_ref,
  is_remainder). Gemini filled all of them (percent 0, a label "null" or
  "is_remainder"), and code refused every plan. The second form is one
  explicit `kind` and one `value`; code converts and checks.
- **tune miss (ap10):** "20% מקדמה, 80% בסיום" came back as 20% + the
  remainder: the same money, a different stage.
- **Seen in the same runs:** a payment word or a place as the unit of a
  work item ("מקדמה", "גג"), shown in the app as a strange unit warning.
  Code now counts only a unit of measure as said.
- **Latency:** most requests 2–6 s; one run had 10–25 s for several
  requests in a row (Gemini side; the same messages took 3 s later).

### Test set (`aplus_test.jsonl`, 20), agents, two runs — 31.10.2026

Run once A+ was complete, prompts as on the tuning set (Intake v5,
Matcher v4.1); nothing tuned after it.

| | Keywords / regex | Run 1 | Run 2 |
|---|---|---|---|
| Conditions recall | 78.8% | 100% | 97.0% |
| Conditions precision | 86.7% | 100% | 97.0% |
| Exact cases | 65% | 100% | 90% |
| Ticked in advance, right | — | 100% | 100% |
| Not-in-library sentences found | 0% | 100% (3/3) | 66.7% (2/3) |
| Payment exact (all 20) | 100% | 100% | 100% |
| Seconds a request | — | 2.8–4.3 (first 12.4) | 2.9–5.2 (first 6.4) |

Run 2 misses: bt11 "the client provides truck parking" → access (medium,
shown unticked with "save as a new condition"), bt20 the payment
condition not suggested for two amount stages (the plan itself right).
No invented plan, no wrong condition ticked in advance. The first request
of a run is slower (server and model warm-up).

### Rerun with `waste_excluded` in the library — 31.10.2026 (afternoon)

The user added "פינוי פסולת אינו כלול במחיר" (key `waste_excluded`,
conflicting with `waste`) and reads "פינוי הפסולת על חשבון המזמין" as that
condition, so ap09 (tune) and bt16 (test) were relabelled (before: a
sentence not in the library). Same prompts; the library now has 16
conditions (`site_ready` too). Keywords split waste like scaffolding.

| | Keywords / regex | Tune | Test run 1 | Test run 2 |
|---|---|---|---|---|
| Conditions recall | 76.5% (test) | 100% | 100% | 100% |
| Conditions precision | 86.7% (test) | 95.5% | 100% | 97.1% |
| Exact cases | 65% (test) | 90% | 100% | 95% |
| Ticked in advance, right | — | 100% | 100% | 100% |
| Not-in-library sentences found | — | 0/1 | 2/2 | 1/2 |
| Payment exact (all cases) | — | 100% | **90%** | 100% |
| Invented payment plan | — | 0 | **1** | 0 |

bt16 and ap09 came back as `waste_excluded` in every run. Misses: tune
ap06 and test bt11 (run 2) → access, medium, unticked (as before). Payment,
test run 1: bt03 "40% בהתחלה, 60% בגמר" → 40% + the remainder (same money,
as ap10 on tune), and **bt06, a message with no payment at all, got an
invented plan "30% + the remainder"** — the first invented plan in any
run. In the app the plan starts unticked (only "סמן הכול" ticks it), so
it would not reach the proposal unnoticed, but it is a real error to
guard against. Not fixed here: the observation comes from the test set
(the code guard came later; see below).

**Labels checked by the domain expert (31.10.2026):** three test cases
(bt11, bt13, bt08) are labelled right. The other A+ labels are the
developer's.

### Payment guard (decision c) — 2.11.2026

The user approved a code check like `keep_stated_quantity`: a percent stage
whose number the message does not say was invented
(`_said_percents_only` in `app/core/validation.py`). Numbers count as said
in digits, words, compound words ("עשרים וחמישה"), and parts of a whole
("חצי", "שליש", "שני שלישים", "רבע", "שלושה רבעים"); one 100% stage alone
is "all at once" ("משלמים הכול בסוף") and stays. A plan with nothing taken
from the message is dropped silently; one with something said and a
percent invented is dropped with the "not clear" warning. "Remainder" has
no number and is never checked.

Seen on the test set (bt06, run 1 of the waste_excluded rerun), so it is
checked on tune and natural only, and **not rerun on aplus_test**. Labels
first, no model: every stage of every tune and natural plan is kept
(6 + 9 plans). Agents, one run each: natural 10/10 exact (was 9/10),
tune 12/12 exact, no invented plan.

## B — review proposal

Counting rule: SPEC 12.3, a finding counts when `(line_code, kind)` match.

| Date | Run | Set | Recall | Precision | Notes |
|---|---|---|---|---|---|
| 30.10 | code checks only (baseline) | review_tune (10 cases, 12 errors) | 75.0% | 100% | 0/3 wording |
| 30.10 | code checks + conflict rule | review_tune | 83.3% | 100% | 1/3 wording (the scaffolding conflict) |
| 30.10 | code checks + conflict rule | review_test (30 cases, 33 errors) | 81.8% | 100% | baseline for the final comparison |
| 30.10 | Reviewer prompt v2 + wording | review_tune | 75.0% | 100% | wording 0/3: the model added none |
| 30.10 | Reviewer prompt v3 | review_tune | 91.7% | 73.3% | wording 2/3, 4 false alarms on catalog wording |
| 30.10 | v3 + catalog-wording marker + conflict rule | review_tune | **100%** | **100%** | 1–2 s per proposal, 1 call |

**30.10, after the domain expert's answers:** the scaffolding and samples rules are
gone ("on request"), the catalog price check is off ("don't alert"), and the
B sets were rebuilt (`scripts/build_review_eval.py`: no price_vs_catalog
errors; contradictions planted from `conflicts`). The runs above are on
the old sets and stay for the record.

| Date | Run | Set | Recall | Precision | Notes |
|---|---|---|---|---|---|
| 30.10 | code checks only (baseline) | review_tune v2 (10 cases, 12 errors) | 75.0% | 100% | 0/3 vague lines |
| 30.10 | code checks only (baseline) | review_test v2 (30 cases, 32 errors) | 75.0% | 100% | 0/8 vague lines; 3/3 conflicts |

The Reviewer ran on review_test v2 on 31.10 (below).

**30.10, ratios only:** the review request no longer carries prices; the
app sends ratios (`eval/client_ratios.py` computes them from the sets the
same way). Code checks only, rerun: review_tune 75.0% / 100%, review_test
75.0% / 100%, identical to the runs above row by row
(`eval/results/2026-10-30_1531_baseline_review_*.json`).

**31.10, validity and VAT are no longer conditions:** the app's PDF always
shows "valid until" and the VAT lines, and the demo wording contradicted it
("prices do not include VAT", "valid 30 days" next to a 14-day choice).
Dropped from `rules.yaml` (always = payment only), from the demo conditions
(16 → 14) and from every proposal and case. The six cases whose planted
error was a removed validity/VAT condition now have payment removed instead
(rt01, rt07, rt09, rx01, rx03, rx23), so each keeps its purpose. Not tuning:
a rule change, decided before any agent run on the test set. Code checks
only, rerun: review_tune 75.0% / 100%, review_test 75.0% / 100%, unchanged
(`eval/results/2026-10-31_0029_baseline_review_*.json`).

The code checks catch 100% of the price, unit and condition errors in every
run, because the same rules planted them; the report says so. What the
Reviewer adds is the wording findings (vague lines) and the phrasing.

### Test set (`review_test.jsonl` v2, 30 cases, 32 errors), Reviewer v3 + marker, two runs — 31.10.2026

Run before any vague phrases from the domain expert were added; a new set
would be a separate, later run. The rules
now include the waste conflict pair; the code-only baseline was rerun on
the same rules first and is unchanged (`2026-10-31_1754_baseline_review_*`).

| Run | Recall | Precision | Missing condition | History price | Unit | Wording (8 vague + 3 conflicts) | Seconds per proposal |
|---|---|---|---|---|---|---|---|
| code checks only (baseline) | 75.0% | 100% | 7/7 | 7/7 | 7/7 | 3/11 | — |
| Reviewer, run 1 (`2026-10-31_1751_review_test.json`) | **100%** | **100%** | 7/7 | 7/7 | 7/7 | 11/11 | 0.8–2.2 (avg 1.4) |
| Reviewer, run 2 (`2026-10-31_1753_review_test.json`) | **100%** | **100%** | 7/7 | 7/7 | 7/7 | 11/11 | 0.7–2.2 (avg 1.5) |

No false alarm and no missed error in either run; one Gemini call per
proposal. The gain over the baseline is the eight vague lines, the part
only the model can judge. Limits, said openly: the vague lines were written
for this project (fictional), and the catalog-wording marker keeps the
model off unedited catalog text by design, so a vague phrase inside the
catalog's own wording is never flagged.

### Reviewer prompt history (`prompts/reviewer.md`)

- **v2 (AI Studio, 29.10):** phrasing only; keeps ratios, units and quotes;
  no money amounts; suggests checking for a typo, never raising or lowering a price.
- **v2 + wording (30.10, tuning set):** the same list carried the phrased
  checks and the new wording findings. The model never added a wording finding.
- **v3 (30.10):** two tasks with two lists in the schema, `findings` (one per
  code check, by number) and `wording` (vague lines, contradictions). The
  model no longer returns `kind` or `line_code` for checks; code takes them
  from the check. Result: wording 2/3, but it called the price list's own
  text vague ("וכו'").
- **v3 + marker (30.10):** lines whose description is exactly the catalog
  text are marked `[נוסח המחירון]` and code drops wording findings on them
  (only an edited description can be vague). Conflicting conditions moved
  to code (`conflicts` in `rules.yaml`), because they have one right answer.

### Seen in the Reviewer's text (not measured, SPEC 12.4)

- Letters of other scripts inside Hebrew words (Georgian, Arabic, niqqud),
  about one per run of 10. Code removes them; the word may stay misspelled.
- Occasional wrong word choice. Each field is one or two sentences, and no
  run named a money amount.

## Gemini limits seen in runs

- Free tier: **15 model calls a minute** for gemini-3.5-flash-lite (a 429
  on 30.10.2026). Agent runs keep to 12 a minute (`CALLS_PER_MINUTE`). The
  server answers 429 with Retry-After: 60 (Hebrew message), and CrewAI's own
  silent retries are off (`max_retry_limit=0`).
