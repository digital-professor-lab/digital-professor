# JSON templates

Blank structure templates for the JSON artifacts this spec defines. Each shows **every field**, including the schema-1.1 additions (`provenance` on every record, the `assumptions` array) and the full Question Schema field set — not just the subset the older `design-example/syllabus_breakdown_template.json` listed.

**Owned by Course Context** (`course-context.md`, *Normative*):

| File | What it templates | Field reference |
|---|---|---|
| `course-context.template.json` | one Course Context file, schema 1.1 (one of each record type) | `course-context.md` §1.2 (fields), §1.3 (IDs), §1.4 (`provenance`) |
| `question-schema.template.json` | one Question Schema, version 1.0 | `course-context.md` §3.2 |

**Shared tutoring records** (`course-context.md` §4, *Proposed, cross-team* — fields not owned solely by Course Context and still subject to agreement):

| File | What it templates | Field reference |
|---|---|---|
| `student-state.template.json` | the running per-session estimate of the student, updated every turn | `course-context.md` §4.1 (Student-State) |
| `gap-record.template.json` | the running diff between the Question Schema (target) and the Student-State (also called Gap/Diagnosis) | `course-context.md` §4.1 (Gap Record) |
| `tutoring-action.template.json` | the decision the Tutoring Engine makes for one turn | `course-context.md` §4.1 (Tutoring Action) |

**Placeholder convention.** String values in `<angle brackets>` describe what to put there, with enum choices listed inline (e.g. `"<source_backed | ai_inferred>"`). Numbers and booleans carry a representative value (`duration_weeks`, `requires_figure`) — replace them. Arrays show one example element; add or remove elements as needed, and use `[]` where the field allows an empty array.

**These are structure templates, not valid instances.** With the placeholders still in them they will not satisfy the Validator (`course-context.validation-and-flagging.md` §3) — the enums, IDs, and links only become valid once filled with real values. For a complete, filled, valid example see `examples/calc1.course-context.json` and `examples/calc1.question-schema.xcosx.json`.
