# Focused evaluation: provisional interpretation

These are independently verified human judgments. 

## What was run

- 46 successful requests, no request errors: 21 handwriting runs and 25 tutoring runs.
- Effective model: `gpt-4o`; handwriting recognition provider: `openai_vision`; five PDF pages supplied as chat text by default; render DPI: 180; citations enabled. Temperature was left at the provider default. Input/output price rates were unset, so cost could not be estimated from the settings snapshot.
- One cold request per modality and one warm batch were recorded. A single cold observation is descriptive, not a stable latency estimate.

## Handwriting

| Case | Handwritten content | Recognition challenge |
|---|---|---|
| h01 | Single minimization objective | Clean baseline equation |
| h02 | Rational function | Fraction and exponents |
| h03 | Iterative update equation | Subscripts and superscripts |
| h04 | Matrix and vector | Two-dimensional mathematical layout |
| h05 | Four-step derivative solution | Preserving step order and line breaks |
| h06 | Linear program with constraints | Inequality signs and nonnegativity constraint |
| h07 | `x₁ + x₂ = 1` | Ambiguous handwritten `1`/`l` subscript |
| h08 | Intentionally incorrect derivative | Transcribing the student's error without correcting it |
| h09 | Convex combination | Multiple stylus ink colors |
| h10 | Lagrangian expression | Variable-width calligraphy strokes |

- Surface exact match: **5/21**; mean character error rate: **0.246**. These figures penalize harmless LaTeX changes such as `$$...$$` versus `\(...\)` and `\min_x` versus `\min_{x}`. They should not be reported alone as mathematical recognition accuracy.
- Draft mathematical equivalence: **16/21**. The model preserved the deliberately wrong derivative in both h08 runs. The substantive misses were h06 first run (`A` became `\hat A`), both h07 runs (the right-hand-side `1` was omitted), and both h10 runs (calligraphic plus signs became commas and `x+y` became `xy`). The multicolor h09 expression remained mathematically correct in both runs.

## Tutoring

- Draft rubric means across 25 responses: correctness **1.16/2**, grounding **0.88/2**, uncertainty handling **1.44/2**. Only **3/25** responses received both full correctness and full grounding scores under the current strict citation rubric.
- The model gave substantially similar answer types across all eight repeated prompts (**8/8 answer families**). This measures stability, not quality: t05, t06, and t08 were consistently problematic.
- For t05 and t06, all six warm responses attributed details to PDF pages 29 or 23 even though chat had only the first five pages of note text. Some answers hedged, but still supplied unsupported page citations. For t02, t03, and t07, the model often cited PDF page 4 for a theorem or standard form printed on page 5.
- On t08, the student did not provide an optimization problem. The model instead chose the syllabus's course-grade optimization problem. That problem really appears on syllabus page 2, but it was not identified by the student as the task. One response also gave values violating its own constraint; another included flawed solver code. The failure is chiefly **request interpretation**, with additional math errors.

## Latency and limitations

| Modality | Cold anchor | Warm same-case timings | Warm all-case median |
|---|---:|---:|---:|
| Handwriting, h01 | 5.84 s | 2.56 s, 4.28 s | 3.56 s (20 runs) |
| Tutoring, t01 | 11.45 s | 7.79 s, 9.97 s, 9.08 s | 6.60 s (24 runs) |

These are end-to-end HTTP wall times. The cold/warm comparison is tentative because there is only one cold request for each modality, and the warm all-case medians mix different inputs. Repeat backend restarts before drawing a performance conclusion.

## Recommended next improvement

Prioritize **page-level retrieval and citation validation** before new interaction features: make the requested note page available to the tutor and reject citations to pages not actually supplied. Then add an instruction/check that asks for the objective and constraints when a student says “solve this problem” without providing one. Keep the h07 and h10 samples as regression cases for handwriting recognition.

## How to review or revise the CSV scores

Open each `*-review.csv` beside its same-prefix `*.jsonl`. Match rows by `run_id`. For handwriting, inspect `reference_markdown` and `transcript`, then set `math_equivalent` to `yes` or `no`; use `failure_tags` for substantive mistakes. For tutoring, compare `response.answer_markdown` and `response.citations` with the case's `expected_points` and source PDF, then score `correctness`, `grounding`, and `uncertainty` from 0 to 2. Give materially equivalent repeated answers the same `answer_family`; use different labels if the substantive answer changes. Separate multiple failure tags with semicolons. The current rows are marked “Draft AI-assisted review” in `notes` so you can replace disputed ratings. Re-run `PYTHONPATH=src python evaluation/evaluate.py summarize` after editing; it reads the review sheets and prints updated figures.
