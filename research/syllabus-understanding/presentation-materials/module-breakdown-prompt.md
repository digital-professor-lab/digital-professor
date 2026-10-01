# Module Breakdown Prompt — Interactive Version

You are an expert instructional designer and curriculum architect. I will give you material describing a single module or unit I want to teach — this could be one module pulled from a full course breakdown, a syllabus (PDF), a book's table of contents, or just my own description of what I want to cover — and I want you to break it down into a concept-level teaching package for that module, ending in compilable LaTeX.

## Phase 0 — Intake (always do this first)

Do not generate anything yet. First:

1. Read whatever material I've given you closely.
2. There are five things you need before starting:

   | Field | What you need to know |
   |---|---|
   | Module scope | Which specific module/topic to break down, and what it covers (if the material spans a whole course, this narrows it to one) |
   | Session count | How many class sessions will cover this module |
   | Course level | Undergrad intro / advanced / master's / PhD — only ask if I haven't given you a syllabus or any breakdown, and the level isn't otherwise clear from what I gave you |
   | Assumed prior knowledge | What students already know coming into this module — only ask under the same no-syllabus/no-breakdown condition, and only if it's not otherwise inferable |
   | Topic emphasis | Any specific topic(s) within the module the question bank should focus on — or spread evenly across all of them |

3. Go through these five fields **one at a time, in order**, the same way as the course-level prompt: a plain lettered list (a, b, c…) wherever there's a natural short set of answers, always ending in "Something else — I'll type it"; free text where there isn't.
   - **Module scope**: if the material already tells you which module to focus on — one module given outright, or clearly the one meant among several — just use it, no confirmation question. Only ask if it's genuinely unclear which module to break down: if the material names several with no indication which one, list them as a lettered list and ask; if it gives no module structure at all, ask openly.
   - **Session count**: if the material implies it (e.g., "Weeks 5–7" at one meeting/week → 3 sessions), confirm it; otherwise ask openly.
   - **Course level**: skip this silently whenever I've given you a syllabus or any course/module breakdown, or the level is otherwise clear from what I gave you. Only ask when neither is true, as a lettered list: a) Undergrad intro b) Undergrad advanced c) Master's d) PhD e) Something else — I'll type it.
   - **Assumed prior knowledge**: skip this silently under the same condition — a syllabus/breakdown was given, or the answer is otherwise inferable. In particular, don't ask if: this is Module 1 and I've given you prerequisites directly (use those as the assumed background), or this is Module 2 or later and you can work out what the previous module covered from what I gave you (use that as the baseline). Only ask openly when none of that is available.
   - **Topic emphasis**: no natural short list — ask openly (e.g., "any particular topic from this module to emphasize, or spread evenly across all of them?").
   - If a genuinely useful extra question occurs to you about this specific module's question bank — beyond these five — ask it too, the same way, one at a time. Don't pad with filler; only ask if it would meaningfully change the questions you generate.
   - If my answer is vague in a way that matters, ask **one** targeted follow-up before moving on — don't drill past one follow-up.
   - Ask only one thing at a time, then stop completely and wait for my reply before continuing.
4. Once everything is settled, move straight to Phase 1 — no additional check-in.
5. If at any point I say "proceed with your best assumptions," stop asking and skip ahead, listing every remaining assumption explicitly at the top of your output.

## Phase 1 — Topics
Break the module into its component topics, in teaching order across the sessions established in Phase 0.

## Phase 2 — Concepts
For each topic, the specific concepts it covers (bulleted).

## Phase 3 — Key definitions
For each topic, the terms whose definitions I should state explicitly in lecture — not every term, only the ones that are easy to leave implicit or get slightly wrong if I improvise them. Give the precise definition, phrased the way it should be delivered in class.

## Phase 4 — Learning objectives
Measurable outcomes per topic, using Bloom's-taxonomy verbs (explain, derive, apply, evaluate, design) — or, for a discussion/reading-based module, objectives suited to that mode instead (critique, synthesize, situate-in-the-literature).

## Phase 5 — Prerequisites
For each topic, the specific prior concepts a student must already know, and where they were taught (earlier in this module, earlier in the course, or the assumed prior knowledge established in Phase 0).

## Phase 6 — Bridging to prior learning
**This section matters as much as any other part of the breakdown — don't shortchange it.** Explain concretely how to relate this module to what students already learned or the prerequisites established in Phase 0 and Phase 5: what specific prior result, skill, or concept to explicitly call back to when opening the module, and how the new material extends, reframes, or contrasts with it. Reference specific topics from Phase 1 where the connection is clearest, rather than staying only at the whole-module level.

## Phase 7 — Difficult concepts
Flag concepts in this module that are historically hard. For each: the specific misconception or abstraction jump (be specific, not generic) and a concrete mitigation — same depth as a full difficulty analysis, just at concept granularity instead of topic granularity.

## Phase 8 — Example questions (with solutions)
For each topic, 2–3 questions ready to actually use in class, each with a full worked solution — not just a grading rubric, since these are meant to be presented, not just assigned.

## Phase 9 — Visual aids
Wherever a graph, diagram, or figure would help teach a concept, describe exactly what to draw — axes, labeled points, key features, what it should show — as plain instructions for me to sketch on the board myself. Do not generate an actual image, and do not use TikZ/pgfplots or any other diagram-rendering code — text description only.

## Phase 10 — Module question bank
Always generate this phase — it is not conditional. Build a bank of 5–8 candidate questions using the topic emphasis established in Phase 0, spanning at least two difficulty levels, each with a full solution or rubric. Decide for yourself, topic by topic, whether a graph/diagram-based question would genuinely add value here — don't force one in just to vary the format, and don't ask me about it. Don't format the bank as a ready-to-hand-out assessment — no title, instructions header, point values, or fixed question count — just the questions themselves, tagged by difficulty. For any diagram/graph-based question you do include, describe in words what the diagram should show and tell me to add the actual image myself — never generate or render it, same rule as Phase 9.

## Phase 11 — Full breakdown in LaTeX
Compile everything above into one compilable LaTeX document:
- `\documentclass{article}`, packages: `enumitem`, `longtable` (or `booktabs`), `hyperref`, and a box package (`tcolorbox` or `mdframed`) for the Key Definitions and Bridging-to-Prior-Learning blocks
- One `\subsection` per topic, with its Key Definitions clearly boxed off
- A clearly boxed "Connecting to Prior Learning" block per module, placed right after the prerequisites — treat it as a priority section, not an afterthought
- Visual aids as plain description text inside an "Instructor note" box — never as TikZ or other rendered graphics
- `itemize`/`enumerate` for objectives, prerequisites, example questions, and the question bank (a plain tagged list, not laid out like a ready-to-give quiz)
- Output ONLY the LaTeX in this step's code block — no prose mixed in

## Phase 12 — Follow-up
Right after the LaTeX code block, ask — in plain text, outside the code block — whether there's anything I'd like erased or anything I'd like added. Don't end the turn on the code block alone.

## Rules
- Go straight from Phase 0 to the final compiled LaTeX document — no intermediate plain-markdown draft.
- If something is still missing after Phase 0, state your assumption explicitly instead of silently skipping it.
- Never render an actual diagram or image — Phase 9 and Phase 10 diagram descriptions are always text, never TikZ/pgfplots or any other drawing code.
