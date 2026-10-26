# Worked Example — Calculus I *(Informative)*

| | |
|---|---|
| **Doc ID** | `example-calc1` |
| **Version** | `0.1.0` |
| **Date** | 2026-10-12 |
| **Owner** | Course Context module (Ovunc) |
| **Status** | *Informative.* It illustrates `course-context.md` on real data; it defines nothing new. Where it and the spec disagree, the spec wins. |
| **Parent spec** | [`course-context.md`](course-context.md) |
| **Data files** | [`examples/calc1.course-context.json`](examples/calc1.course-context.json), [`examples/calc1.question-schema.xcosx.json`](examples/calc1.question-schema.xcosx.json) |
| **Full interactive version** | the design page `digital-professor-design.html` — the two schemas, the tutoring-flow diagram, and the 13-turn trace rendered as a conversation |

This document walks one course end to end: the generated **Course Context** file, the **Question Schema** built from it for a student's question, where every field came from, and the **tutoring workflow** that question drives (Question Schema → Student-State → Gap Record → Tutoring Action). The shared tutoring records are defined in `course-context.md` §4 and templated in `templates/`.

---

## 1. The Course Context file

`examples/calc1.course-context.json` is the team's `calc1_course_schema.json` (generated from the one-page syllabus by the syllabus-to-JSON prompt) plus the `provenance` field. Removing it and restoring `schema_version` 1.0 gives back the original data exactly. It has 6 modules, 33 concepts, 33 objectives, 32 sources, 66 questions and 19 assumptions. All 31 syllabus section references appear as Source records; the 32nd, 3.6, is a derived source for the formal limit definition.

| Module ID | Title | Weeks | Concepts | Questions |
|---|---|---|---|---|
| `calc1.01-functions` | Review Basic Properties of Functions | 1-2 | 4 | 8 |
| `calc1.02-limits` | Limits and Continuity | 3-4 | 6 | 12 |
| `calc1.03-derivatives` | Derivatives | 5-7 | 11 | 22 |
| `calc1.04-diff-applications` | Applications of Differentiation | 8-10 | 5 | 10 |
| `calc1.05-integration` | Integration | 11-12 | 4 | 8 |
| `calc1.06-integral-applications` | Applications of the Integral | 13-14 | 3 | 6 |

Prerequisite chain behind the example question: `by-parts` requires `substitution` and `product-quotient`; `substitution` requires `ftc`, `chain-rule` and `antiderivatives`.

The records the Question Schema below is built from (abridged to the fields used; all values are exactly as in the file):

```json
{
  "Concept": {
    "id": "calc1.06-integral-applications.by-parts",
    "module_id": "calc1.06-integral-applications",
    "name": "Integration by parts",
    "summary": "∫ u dv = uv - ∫ v du reverses the product rule. Choose u to simplify when differentiated (LIATE heuristic); it can be repeated and applied to definite integrals.",
    "key_definitions": [
      "Integration by parts formula",
      "LIATE heuristic for choosing u",
      "Definite integration by parts"
    ],
    "prerequisite_ids": [
      "calc1.06-integral-applications.substitution",
      "calc1.03-derivatives.product-quotient"
    ],
    "objective_ids": [
      "calc1.06-integral-applications.by-parts.lo1"
    ],
    "difficulty_notes": [
      {
        "misconception": "Choosing u and dv so the new integral is harder than the original.",
        "mitigation": "Use LIATE and test both choices on a simple case like ∫ x e^x dx."
      },
      {
        "misconception": "Sign errors or forgetting to integrate dv to get v.",
        "mitigation": "Tabulate u, du, dv, v in a 2x2 grid before substituting."
      }
    ],
    "source_ids": [
      "neuhauser.s7-2"
    ],
    "question_ids": [
      "calc1.06-integral-applications.by-parts.q1",
      "calc1.06-integral-applications.by-parts.q2"
    ],
    "provenance": "ai_inferred"
  },
  "LearningObjective": {
    "id": "calc1.06-integral-applications.by-parts.lo1",
    "concept_id": "calc1.06-integral-applications.by-parts",
    "text": "Choose u and dv sensibly and evaluate integrals using integration by parts.",
    "bloom_level": "apply",
    "provenance": "ai_inferred"
  },
  "Source": {
    "id": "neuhauser.s7-2",
    "type": "textbook",
    "citation": "Neuhauser, C. & Roper, M. Calculus for Biology and Medicine, 4th ed. Pearson, 2018.",
    "section": "Section 7.2",
    "text_chunk": "Syllabus entry: 7.2 Integration by Parts and Practicing Integration",
    "provenance": "source_backed"
  },
  "AssessmentQuestion (one of two)": {
    "id": "calc1.06-integral-applications.by-parts.q1",
    "concept_ids": [
      "calc1.06-integral-applications.by-parts"
    ],
    "objective_ids": [
      "calc1.06-integral-applications.by-parts.lo1"
    ],
    "type": "quiz",
    "difficulty": "recall",
    "prompt": "Evaluate ∫ x e^x dx.",
    "solution": "Let u = x, dv = e^x dx, so du = dx and v = e^x. Then ∫ x e^x dx = x e^x - ∫ e^x dx = x e^x - e^x + C.",
    "rubric": "1 pt for the choice of u and dv; 1 pt for the formula; 1 pt for the final answer.",
    "common_wrong_answers": [
      "(x^2/2)e^x + C",
      "x e^x + e^x + C"
    ],
    "requires_figure": false,
    "provenance": "ai_inferred"
  }
}
```

## 2. The Question Schema for "∫ x cos(x) dx"

A student brings `\int x\cos(x) dx`. It is not in the question bank (the nearest question on the same concept is `by-parts.q1`, ∫ x e^x dx), so the builder runs the runtime path of `course-context.md` §3.3: `origin = runtime`.

`examples/calc1.question-schema.xcosx.json`:

```json
{
  "question_schema_version": "1.0",
  "question_id": "calc1.06-integral-applications.by-parts.adhoc-d7df1b60",
  "origin": "runtime",
  "course_id": "calc1",
  "module_id": "calc1.06-integral-applications",
  "concept_ids": [
    "calc1.06-integral-applications.by-parts"
  ],
  "prompt": "\\int x\\cos(x) dx",
  "learning_objectives": [
    {
      "id": "calc1.06-integral-applications.by-parts.lo1",
      "text": "Choose u and dv sensibly and evaluate integrals using integration by parts.",
      "bloom_level": "apply"
    }
  ],
  "prerequisite_concepts": [
    {
      "concept_id": "calc1.06-integral-applications.substitution",
      "name": "The substitution rule",
      "relevance": "Needed to rule substitution out: the student must be able to test whether one factor of the integrand is a constant multiple of the derivative of an inner function.",
      "provenance": "ai_inferred",
      "derived_from": "runtime"
    },
    {
      "concept_id": "calc1.03-derivatives.product-quotient",
      "name": "Product and quotient rules",
      "relevance": "Integration by parts reverses the product rule, and the answer can be checked by differentiating with it.",
      "provenance": "ai_inferred",
      "derived_from": "runtime"
    }
  ],
  "correct_approach": {
    "technique": "Integration by parts with u = x and dv = cos(x) dx",
    "justification": "The integrand is a product of an algebraic factor and a trigonometric factor with no derivative relationship between them, so the substitution test fails. Taking u = x lets differentiation simplify it (du = dx) while dv = cos(x) dx integrates cleanly (v = sin(x)), which is the LIATE choice for this concept."
  },
  "alternative_approaches": [
    {
      "technique": "Integration by parts, tabular (DI) bookkeeping: D column x, 1, 0; I column cos(x), sin(x), -cos(x)",
      "justification": "Same technique with different bookkeeping. The D column reaches 0 after one step, so the table terminates.",
      "provenance": "ai_inferred",
      "derived_from": "runtime"
    }
  ],
  "reference_solution": "Take u = x and dv = cos(x) dx, so du = dx and v = sin(x). Then the integral of x cos(x) dx = x sin(x) - integral of sin(x) dx = x sin(x) + cos(x) + C. Check: d/dx[x sin(x) + cos(x)] = sin(x) + x cos(x) - sin(x) = x cos(x).",
  "common_misconceptions": [
    {
      "description": "Choosing u and dv so the new integral is harder than the original.",
      "cue": "The student sets u = cos(x) and dv = x dx, and the new integral of (x^2/2) sin(x) dx is more complicated than the one they started with.",
      "mitigation": "Use LIATE and test both choices on a simple case like ∫ x e^x dx.",
      "provenance": "ai_inferred",
      "derived_from": "calc1.06-integral-applications.by-parts#difficulty_notes[0]"
    },
    {
      "description": "Sign errors or forgetting to integrate dv to get v.",
      "cue": "The student reports x sin(x) - cos(x) + C, or writes v = cos(x) or v = -sin(x) when dv = cos(x) dx.",
      "mitigation": "Tabulate u, du, dv, v in a 2x2 grid before substituting.",
      "provenance": "ai_inferred",
      "derived_from": "calc1.06-integral-applications.by-parts#difficulty_notes[1]"
    },
    {
      "description": "Reaching for u-substitution because an x sits next to a trigonometric factor, without checking whether x is a constant multiple of the derivative of an inner function.",
      "cue": "The student says they tried u-substitution (for example u = cos(x) or u = x^2) and it did not simplify.",
      "provenance": "ai_inferred",
      "derived_from": "runtime"
    }
  ],
  "source_reference": {
    "concept_ids": [
      "calc1.06-integral-applications.by-parts"
    ],
    "source_ids": [
      "neuhauser.s7-2"
    ],
    "sibling_question_ids": [
      "calc1.06-integral-applications.by-parts.q1"
    ],
    "citation": "Neuhauser, C. & Roper, M. Calculus for Biology and Medicine, 4th ed. Pearson, 2018. Section 7.2",
    "grounding": "reference_only"
  },
  "provenance": "ai_inferred",
  "built_from": {
    "course_context_schema_version": "1.1",
    "content_sha256": "5f162f061c39750235b93b5875900366d8ab6bbdff0e84973cc0494b2a2d3eac"
  }
}
```

## 3. Where each field came from

| Field | Kind | From |
|---|---|---|
| `course_id`, `module_id`, `concept_ids` | retrieved | concept match to `by-parts` (step 3), then its Course Context record |
| `prompt` | verbatim | the student's text |
| `learning_objectives` | copied | `by-parts.lo1` |
| `prerequisite_concepts[].concept_id`, `name` | copied | `Concept.prerequisite_ids` of `by-parts` |
| `prerequisite_concepts[].relevance` | runtime | builder |
| `correct_approach`, `alternative_approaches`, `reference_solution` | runtime | builder, from the concept summary and the sibling `by-parts.q1`; the answer was checked by differentiating it |
| `common_misconceptions[0]`, `[1]` | copied + cue written | `by-parts` `difficulty_notes[0]` and `[1]` |
| `common_misconceptions[2]` | runtime | builder (not in Course Context, see §5) |
| `source_reference` | retrieved | `Concept.source_ids` of `by-parts`; `grounding: reference_only` because the file holds only a syllabus line for Section 7.2 |
| `provenance`, `built_from` | derived | weakest link (`ai_inferred`); SHA-256 of the Course Context file |

## 4. The tutoring workflow on this question

Once the Question Schema above is built and handed to the Tutoring Engine, a session runs the loop from `course-context.md` §4: each turn compares the **Student-State** (the running estimate, updated from student evidence) against the Question Schema (the fixed target), writes a **Gap Record** of what is still open, and the engine emits one **Tutoring Action** aimed at the top open gap. The session is resolved when `open_gaps` is empty. Blank shapes for these records are in `templates/student-state.template.json`, `gap-record.template.json`, and `tutoring-action.template.json`.

`∫ x cos(x) dx` is a good test because it *looks* like substitution but needs integration by parts — exactly the misconception the Question Schema's `common_misconceptions[2]` is watching for.

**Before the session.** The Question Schema is fully populated (§2). The Student-State starts empty, so every comparable target slot is an open gap.

**The 13-turn trace** (condensed from the design page; the three prerequisite/misconception labels P1, P2, P3 and M1 are the design page's shorthand — see §5 for how they map onto Course Context records):

| Turn | Action | What happens | Student-State update |
|---|---|---|---|
| 1 | Elicit | DP asks what the student tried and where they got stuck; they tried u-substitution and it didn't simplify | `observed_approach` ← u-substitution; `stated_reasoning` ← tried u-sub, stuck |
| 2 | Diagnose *(internal)* | `observed_approach` vs `correct_approach.technique` → mismatch; matches the M1 surface-pattern cue | `suspected_misconception` ← {M1, tentative} |
| 3 | Contrast | DP hands a genuine u-sub integral, ∫ x e^(x²) dx; the student solves it with u = x² | `prerequisite_status[substitution]` ← confirmed; `components_correct` += u-sub mechanics |
| 4 | Probe | "Are the two integrals structurally the same?" the student senses they differ but can't say why | `prerequisite_status[substitution]` ← partially demonstrated |
| 5 | Explain | DP explains the derivative-relationship test: x is not a multiple of the derivative of anything inside cos x | `prerequisite_status[substitution]` ← confirmed (assisted) |
| 6 | Probe | "What other technique might work?" the student proposes integration by parts (beside a wrong guess) | `observed_approach` ← integration by parts (tentative) |
| 7 | Probe + Explain | The wrong guess (trig sub) is ruled out; integration by parts confirmed as the approach | `suspected_misconception` ← resolved; `observed_approach` ← integration by parts (confirmed); `evidence_of_understanding_level` ← 1 |
| 8 | Retry | The student applies the formula but picks u = cos x, dv = x dx; the new integral gets harder | `prerequisite_status[by-parts choice]` ← partially demonstrated (formula right, choice backwards) |
| 9 | Hint | "Is the new integral simpler or more complicated than what you started with?" | `suspected_misconception` refined: no check that the u,dv choice makes progress |
| 10 | Retry | The student swaps to u = x, dv = cos x dx → x sin x + cos x + C | `prerequisite_status[by-parts choice]` ← confirmed (assisted); `components_correct` += executes IBP correctly |
| 11 | Verify | The tutor differentiates the answer and gets back x cos x | `components_correct` += final answer verified |
| 12 | Check understanding | "Why did swapping u and dv work?" the student states the heuristic | `evidence_of_understanding_level` ← 4 |
| 13 | Transfer | Two take-home problems: ∫ x sin x dx and ∫ x e^(−x²) dx | `interventions_attempted` += Transfer; level can reach 5 once they return |

**Behind one turn — Turn 9.** The dialogue above is the surface; underneath, the engine reads a Gap Record and emits a Tutoring Action.

Gap Record entering Turn 9:

```json
{
  "question_id": "calc1.06-integral-applications.by-parts.adhoc-d7df1b60",
  "open_gaps": [
    { "target_slot": "by-parts formula & u,dv choice", "requirement": "apply integration by parts with a u,dv choice that makes the integral simpler", "status": "partial", "evidence": "formula applied correctly, but u = cos x, dv = x dx was chosen and the new integral got more complex" },
    { "target_slot": "evidence_of_understanding_level", "requirement": "reach level 5 (transfer)", "status": "open", "evidence": "recognizes and is executing the technique; not yet transferred" }
  ],
  "closed_gaps": [
    { "target_slot": "correct_approach.technique", "requirement": "integration by parts", "status": "closed", "evidence": "confirmed at Turn 7" },
    { "target_slot": "common_misconceptions[2] (M1)", "requirement": "resolve the surface-pattern misconception", "status": "closed", "evidence": "resolved at Turn 7" },
    { "target_slot": "prerequisite: substitution mechanics", "requirement": "reverse the chain rule", "status": "closed", "evidence": "confirmed at Turn 3" },
    { "target_slot": "prerequisite: structural test", "requirement": "test whether substitution applies", "status": "closed", "evidence": "confirmed (assisted) at Turn 5" }
  ],
  "off_target_context": ["interventions_attempted = [Elicit, Diagnose, Contrast, Probe, Explain, Probe, Probe+Explain, Retry]"],
  "resolved_when": "open_gaps is empty"
}
```

Tutoring Action emitted for Turn 9:

```json
{
  "action": "hint",
  "target_gap": "by-parts formula & u,dv choice",
  "goal": "get the student to notice the new integral is more complex, and infer on their own that the u,dv choice is backwards",
  "constraints": ["do not reveal the correct u,dv", "one hint only", "keep it a question (Socratic)"],
  "rationale": "the formula mechanics are already sound, so don't re-teach them; the gap is the selection heuristic, so prompt self-correction rather than explain"
}
```

**Final Gap Record (after Turn 13).** Only the comparable slots are scored; the session resolves when none are open. The gap-status mapping is `course-context.md` §4.1; the turn-by-turn evolution is §4.2.

| Target slot | Target | Student-State (final) | Gap |
|---|---|---|---|
| technique | integration by parts | integration by parts, executed | closed |
| prerequisite: substitution mechanics | required | confirmed | closed |
| prerequisite: structural test | required | confirmed (assisted) | partial — not yet independent |
| by-parts formula & u,dv choice | required | confirmed (assisted) | partial — needed one hint |
| M1 misconception | watch for | resolved | closed |
| evidence level | 5 (transfer) | 4 (explains why) | partial — awaiting the Turn-13 answers |

`open_gaps` is not empty (the structural test, the u,dv choice, and the evidence level are still partial), so the session is not over at Turn 13. The full conversation, with both schema panes filling in turn by turn, is on the design page `digital-professor-design.html`.

## 5. What the tutoring trace expects that Course Context does not hold

The design page's 13-turn trace was written before this file existed and assumes richer content:

| In the trace | In Course Context | V1 handling |
|---|---|---|
| M1: pattern-matching "x next to a trig factor" to u-substitution | no such note (`substitution` notes: leaving x's in after substituting, dropping a constant factor; `by-parts` notes: a harder integral, sign errors) | builder adds it as a runtime misconception, `ai_inferred` |
| LO1: choose a technique from the structure of the integrand | `by-parts` has one objective: choose u and dv sensibly and evaluate | not added; the Question Schema carries only what Course Context holds |
| P2: the structural test for substitution | not its own concept; part of `substitution` | recorded as `relevance` text on the `substitution` prerequisite |
| P3 listed as a *prerequisite* (the by-parts formula and the u and dv choice) | it is the target concept `by-parts` itself | tracked through `observed_approach`, not `prerequisite_status` (`course-context.md` open question 4) |
| IDs such as `calc1.module-F.q-xcosx-01` | `calc1.06-integral-applications…` | Course Context IDs are canonical (`course-context.md` open question 3) |
| `source_reference`: "difficulty note on technique-selection confusion" | no such note | cites Section 7.2 as reference-only |

## 6. Known deviations of this example from the spec

| Item | Detail | Reference |
|---|---|---|
| Labelled syllabus lines in `text_chunk` | all 32 Source records: 31 start `Syllabus entry:`, one starts `Syllabus reference:` | `course-context.md` open question 2 |
| `Source.type = textbook` on reference-only records | no textbook text is held | `course-context.md` open question 2 |
| Wildcard assumptions | 3 entries use `id` = `calc1.*`; one `field` is `format (no schema field)` | allowed by P-4 |
| `duration_weeks = 14` | the syllabus units sum to about 12 | inferred; logged in `assumptions` |
| Module and Concept IDs in the design page's trace | `calc1.module-F…` rather than `calc1.06-…` | `course-context.md` open question 3 |
