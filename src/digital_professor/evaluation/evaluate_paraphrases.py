#!/usr/bin/env python3
"""Supplementary wording checks on the two known evidence cases, not held-out topics."""
import json
from digital_professor.paths import BENCHMARK
from digital_professor.retrieval.search import Retriever
from .run_benchmark import DATA,HERE,load_jsonl,score_case

def main():
    cases={c['id']:c for c in load_jsonl(BENCHMARK / 'benchmark_50.jsonl')}
    examples=[('Q11','Which theorem helps evaluate limits of damped oscillations, and where does the course use it?'),('Q11','Which limit theorem handles oscillatory functions, and how is it applied to population models?'),('Q11','Identify the limit theorem for damped population signals and its course applications.'),('Q18','Compare continuous population differential-equation models with the discrete logistic equation and its long-term behavior.'),('Q18','Contrast the discrete logistic map with introductory differential equations for population growth.'),('Q18','Compare the long-run behavior of a discrete logistic model with continuous population growth modeled by differential equations.')]
    ps={p['passage_id']:p for p in load_jsonl(DATA/'passages.jsonl')};ds={d['document_id']:d for d in load_jsonl(DATA/'documents.jsonl')}
    with Retriever() as r:
     reports=r.search_many([q for _,q in examples])
    out=[]
    for i,((original,q),report) in enumerate(zip(examples,reports),1):
     c=dict(cases[original],id=f'P{i}',question=q)
     scored=score_case(c,report,ps,ds,{})
     out.append({'question':q,'original_evidence_case':original,'report':report,'evaluation':scored})
     print(c['id'],scored['complete_at']['6'],scored['group_first_ranks'],flush=True)
    (HERE/'paraphrase_validation.json').write_text(json.dumps({'limits':'New wording of the same two known evidence cases, not independent-topic validation. No labels enter search.','cases':out},indent=2)+'\n')

if __name__ == "__main__":
    main()
