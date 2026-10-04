#!/usr/bin/env python3
"""Freeze 50 source-anchored English retrieval questions before model evaluation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


from digital_professor.paths import CATALOG, BENCHMARK
HERE = BENCHMARK
HERE.mkdir(parents=True, exist_ok=True)
DATA = CATALOG


def a(source_type: str, start_line: int) -> tuple[str, int]:
    return source_type, start_line


# Each nested list is one required evidence group; alternatives within a group are OR.
# Version 2 rebalances source roles after a version-1 coverage audit. Its anchors
# are fixed before version-2 model runs; the complete version-1 run is archived.
SPECS = [
    # Calculus I: eight easy questions.
    ("calc1", "easy", "Which function topics, growth models, and sequences are introduced in syllabus Module 1?", [[a("syllabus", 124)]]),
    ("calc1", "easy", "Which algebra, graphing, geometry, and trigonometry skills are prerequisites before Calculus I?", [[a("context", 123)]]),
    ("calc1", "easy", "Which discrete population model is used to identify an equilibrium?", [[a("textbook_reference", 373)]]),
    ("calc1", "easy", "Which major limit and continuity topics appear in the Chapter 3 course context?", [[a("context", 241)]]),
    ("calc1", "easy", "Which differentiation rule handles a composite function?", [[a("textbook_reference", 469)]]),
    ("calc1", "easy", "Which extrema, monotonicity, and optimization topics are listed in syllabus Module 4?", [[a("syllabus", 277)]]),
    ("calc1", "easy", "Which two parts of the Fundamental Theorem of Calculus appear in the Chapter 6 course context?", [[a("context", 365)]]),
    ("calc1", "easy", "Which integration objective concerns the average value of a function on an interval?", [[a("textbook_reference", 579)]]),
    # Calculus I: nine medium questions.
    ("calc1", "medium", "How does the course distinguish power-law relationships from exponential growth and then linearize data?", [[a("textbook_reference", 326)], [a("textbook_reference", 333)]]),
    ("calc1", "medium", "How do the Beverton-Holt equilibrium and derivative-based stability of a recurrence connect?", [[a("textbook_reference", 373)], [a("textbook_reference", 528)]]),
    ("calc1", "medium", "Which limit theorem is used with oscillating or damped models, and where does the course apply it?", [[a("context", 241), a("textbook_reference", 421)], [a("textbook_reference", 429)]]),
    ("calc1", "medium", "How does the course interpret a derivative as velocity, reaction rate, or growth rate?", [[a("context", 278), a("textbook_reference", 464)]]),
    ("calc1", "medium", "How are critical points classified using the first or second derivative tests?", [[a("textbook_reference", 523)]]),
    ("calc1", "medium", "How does syllabus Module 2 connect the Intermediate-Value Theorem with finding roots by bisection?", [[a("syllabus", 169)], [a("textbook_reference", 423)]]),
    ("calc1", "medium", "How do Riemann sums lead to a definite integral and then to the Fundamental Theorem?", [[a("syllabus", 326), a("textbook_reference", 571)], [a("textbook_reference", 574)]]),
    ("calc1", "medium", "How is a definite integral used for cumulative population change or total drug absorption?", [[a("context", 365), a("textbook_reference", 578)], [a("textbook_reference", 587)]]),
    ("calc1", "medium", "Which rules combine to differentiate a product containing a composite function?", [[a("textbook_reference", 467)], [a("textbook_reference", 469)]]),
    # Calculus I: six hard answerable questions, one scope trap, one absent fact.
    ("calc1", "hard", "Compare the discrete logistic equation's long-term behavior with the course's introductory continuous population differential-equation models.", [[a("textbook_reference", 374)], [a("textbook_reference", 530)]]),
    ("calc1", "hard", "Trace a density-dependent population recurrence from its model to equilibrium stability via derivatives.", [[a("textbook_reference", 372), a("textbook_reference", 373)], [a("textbook_reference", 528)]]),
    ("calc1", "hard", "Relate FTC Part I, FTC Part II, and the interpretation of an integral as cumulative change.", [[a("textbook_reference", 574)], [a("textbook_reference", 577)], [a("textbook_reference", 578)]]),
    ("calc1", "hard", "How do related rates and linear approximation use derivatives to handle changing or uncertain measurements?", [[a("textbook_reference", 472)], [a("textbook_reference", 479)]]),
    ("calc1", "hard", "Connect allometric power functions, logarithmic plots, and the treatment of growth data in the course.", [[a("context", 171), a("textbook_reference", 326)], [a("textbook_reference", 333)], [a("context", 206)]]),
    ("calc1", "hard", "How do limit laws and derivative rules prepare students to apply L'Hopital's Rule to indeterminate forms?", [[a("context", 241), a("textbook_reference", 416)], [a("textbook_reference", 526)]]),
    ("calc1", "hard", "What does the Calculus II material say about contour plots and gradients in multivariable calculus?", "scope_excluded", a("context", 516)),
    ("calc1", "hard", "What exact words did the instructor say during the lecture on September 12, 2026?", "absent", "No verified lecture transcript or dated lecture recording is supplied."),
    # Number Theory I: eight easy questions.
    ("number_theory_1", "easy", "Which properties of Dedekind domains are listed in the first syllabus module?", [[a("syllabus", 90)]]),
    ("number_theory_1", "easy", "What algebraic structure do fractional ideals have under multiplication?", [[a("textbook_reference", 71)]]),
    ("number_theory_1", "easy", "Which groups and efg identity appear in the Galois-theory course context?", [[a("context", 186)]]),
    ("number_theory_1", "easy", "How is the discriminant related to the different in the course outline?", [[a("textbook_reference", 132)]]),
    ("number_theory_1", "easy", "Which p-adic, valuation, and completion topics are in Unit 3 of the course context?", [[a("context", 228)]]),
    ("number_theory_1", "easy", "What rank does Dirichlet's unit theorem assign to the free part of the unit group?", [[a("textbook_reference", 283)]]),
    ("number_theory_1", "easy", "Which restricted-product and idele topics are covered in syllabus Module 5?", [[a("syllabus", 158)]]),
    ("number_theory_1", "easy", "What quotient defines the idele class group?", [[a("textbook_reference", 350)]]),
    # Number Theory I: nine medium questions.
    ("number_theory_1", "medium", "How does prime-ideal decomposition in an extension relate to e and f in the fundamental identity?", [[a("textbook_reference", 92)], [a("textbook_reference", 112)]]),
    ("number_theory_1", "medium", "How do decomposition groups, inertia groups, and Frobenius organize prime splitting?", [[a("context", 186)], [a("syllabus", 107)]]),
    ("number_theory_1", "medium", "How does syllabus Module 4 connect the product formula, Minkowski geometry, and unit groups?", [[a("syllabus", 141)]]),
    ("number_theory_1", "medium", "How do p-adic completion and Hensel's lemma support local field calculations?", [[a("context", 228)], [a("textbook_reference", 220)]]),
    ("number_theory_1", "medium", "How does the course context connect Minkowski theory to class-number finiteness?", [[a("context", 186)]]),
    ("number_theory_1", "medium", "How are the idele class group and the compact norm-one idele class group related?", [[a("textbook_reference", 350)], [a("textbook_reference", 370)]]),
    ("number_theory_1", "medium", "How does syllabus Module 5 lead from restricted products to ideles and adelic topology?", [[a("syllabus", 158)], [a("textbook_reference", 308)]]),
    ("number_theory_1", "medium", "How do local zeta integrals and global Poisson summation enter the optional Tate's Thesis module?", [[a("syllabus", 175), a("textbook_reference", 415)], [a("textbook_reference", 456)]]),
    ("number_theory_1", "medium", "Which algebra prerequisites support understanding decomposition and inertia groups?", [[a("syllabus", 35)], [a("context", 186)]]),
    # Number Theory I: six hard answerable questions, one scope trap, one absent fact.
    ("number_theory_1", "hard", "Trace Dedekind-domain conditions through fractional-ideal factorization to splitting of primes in extensions.", [[a("textbook_reference", 50)], [a("textbook_reference", 71)], [a("textbook_reference", 92)]]),
    ("number_theory_1", "hard", "Relate the different and discriminant to ramification, then locate the broader Riemann-Hurwitz treatment.", [[a("textbook_reference", 132)], [a("context", 270)]]),
    ("number_theory_1", "hard", "Connect the global product formula with the topology of ideles and the idele class group.", [[a("syllabus", 141), a("textbook_reference", 242)], [a("textbook_reference", 350)]]),
    ("number_theory_1", "hard", "How do Minkowski's lattice argument and Dirichlet's unit theorem address distinct finiteness or structure questions?", [[a("textbook_reference", 262)], [a("textbook_reference", 283)]]),
    ("number_theory_1", "hard", "How do adelic self-duality and Haar-measure volume computations fit together in this course?", [[a("textbook_reference", 329)], [a("textbook_reference", 391)]]),
    ("number_theory_1", "hard", "Relate the local functional equation and L-factors to global zeta integrals and Poisson summation in Tate's Thesis.", [[a("syllabus", 175), a("textbook_reference", 435)], [a("textbook_reference", 456)]]),
    ("number_theory_1", "hard", "What does the unconfirmed second-semester Unit 11 say about global class field theory?", "scope_excluded", a("context", 559)),
    ("number_theory_1", "hard", "What score did student Alice Smith receive on the first problem set?", "absent", "No individual student records or graded submissions are supplied."),
]


def main() -> None:
    documents = [json.loads(line) for line in (DATA / "documents.jsonl").read_text(encoding="utf-8").splitlines()]
    passages = [json.loads(line) for line in (DATA / "passages.jsonl").read_text(encoding="utf-8").splitlines()]
    docs = {row["document_id"]: row for row in documents}
    anchors = {}
    for passage in passages:
        doc = docs[passage["document_id"]]
        key = (doc["course_id"], doc["source_type"], passage["start_line"])
        # Textbook tables can have both a whole-table passage and a one-line row
        # starting at the same line; prefer the narrower evidence unit.
        previous = anchors.get(key)
        if previous is None or passage["end_line"] - passage["start_line"] < previous["end_line"] - previous["start_line"]:
            anchors[key] = passage

    cases = []
    for number, spec in enumerate(SPECS, start=1):
        course, difficulty, question, evidence, *extra = spec
        item = {"id": f"Q{number:02d}", "course_id": course, "difficulty": difficulty, "question": question}
        if isinstance(evidence, list):
            item["kind"] = "answerable"
            groups = []
            for group in evidence:
                candidates = []
                for source_type, line in group:
                    passage = anchors[(course, source_type, line)]
                    assert passage["scope_status"] == "pilot_course_or_general", item["id"]
                    assert passage["readable_text"].strip(), item["id"]
                    candidates.append({"passage_id": passage["passage_id"], "source_type": source_type,
                                       "filename": docs[passage["document_id"]]["filename"],
                                       "start_line": passage["start_line"], "end_line": passage["end_line"]})
                groups.append(candidates)
            item["required_evidence_groups"] = groups
        elif evidence == "scope_excluded":
            item["kind"] = evidence
            source_type, line = extra[0]
            passage = anchors[(course, source_type, line)]
            assert passage["scope_status"] != "pilot_course_or_general"
            item["excluded_anchor"] = {"passage_id": passage["passage_id"],
                                       "scope_status": passage["scope_status"],
                                       "filename": docs[passage["document_id"]]["filename"],
                                       "start_line": passage["start_line"]}
        else:
            item["kind"] = "absent"
            item["absence_reason"] = extra[0]
        cases.append(item)

    assert len(cases) == 50
    assert Counter((case["course_id"], case["difficulty"]) for case in cases) == {
        (course, level): expected for course in ("calc1", "number_theory_1")
        for level, expected in (("easy", 8), ("medium", 9), ("hard", 8))
    }
    assert Counter(case["kind"] for case in cases) == {"answerable": 46, "scope_excluded": 2, "absent": 2}
    path = HERE / "benchmark_50.jsonl"
    path.write_text("".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases), encoding="utf-8")
    manifest = {"version": 2, "question_count": len(cases),
                "revision_reason": "Rebalanced syllabus and context evidence after version-1 source-role coverage audit; retrieval code and settings unchanged.",
                "previous_dataset_sha256": "b0151e5bfae7a36a444c5987b27a6577c2cd7ef4bd09ae634df637aab283cc0f",
                "distribution": dict(Counter(case["kind"] for case in cases)),
                "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_manifest_sha256": hashlib.sha256((DATA / "manifest.json").read_bytes()).hexdigest(),
                "status": "source_anchored_silver_labels_pending_instructor_review"}
    (HERE / "benchmark_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
