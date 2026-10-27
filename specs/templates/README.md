# JSON templates

Blank structure templates for the JSON artifacts this spec defines. Each shows **every field**, including the schema-1.1 additions (`provenance` on every record, the `assumptions` array) and the full Question Schema field set — not just the subset the older `design-example/syllabus_breakdown_template.json` listed.

**Owned by Course Context** (`course-context.md`, *Normative*):

| File | What it templates | Field reference |
|---|---|---|
| `course-context.template.json` | one Course Context file, schema 1.1 (one of each record type) | `course-context.md` §1.2 (fields), §1.3 (IDs), §1.4 (`provenance`) |
| `question-schema.template.json` | one Question Schema, version 1.0 | `course-context.md` §3.2 |

**Shared tutoring records** (canonical in [`../interfaces.md`](../interfaces.md); *Proposed, cross-team* — not owned by Course Context). These carry the common record envelope (interfaces.md §1.1):

| File | What it templates | Field reference |
|---|---|---|
| `learner-state.template.json` | the Tutoring Engine's running interpretation of the student **plus** the running gap diff against the Question Schema (the former "Student-State" + "Gap Record", merged) | `interfaces.md` §10 (`LearnerState`) |
| `tutoring-action.template.json` | the decision the Tutoring Engine makes for one turn (`action_type` = this module's 12-verb vocabulary) | `interfaces.md` §11 (`TutoringAction`) |

**Common envelope.** `learner-state` and `tutoring-action` are pure exchanged records, so they include the common envelope (`record_id`, `record_type`, `schema_version`, …; interfaces.md §1.1). `course-context` and `question-schema` show the **payload** — these are built artifacts hashed by value (`built_from.content_sha256`), so the envelope (which carries a timestamp) is added only when the record is exchanged, not stored in the file.

**Placeholder convention.** String values in `<angle brackets>` describe what to put there, with enum choices listed inline (e.g. `"<source_backed | ai_inferred>"`). Numbers and booleans carry a representative value (`duration_weeks`, `requires_figure`) — replace them. Arrays show one example element; add or remove elements as needed, and use `[]` where the field allows an empty array.

**These are structure templates, not valid instances.** With the placeholders still in them they will not satisfy the Validator (`course-context.validation-and-flagging.md` §3) — the enums, IDs, and links only become valid once filled with real values. For a complete, filled, valid example see `examples/calc1.course-context.json` and `examples/calc1.question-schema.xcosx.json`.
