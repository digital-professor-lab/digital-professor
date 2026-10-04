#!/usr/bin/env python3
"""Compare full-query and facet retrieval; preserve all earlier reports."""
import hashlib
import json
import time
from datetime import datetime, timezone
from .run_benchmark import DATA, HERE, load_jsonl, score_case, summarize
from digital_professor.paths import BENCHMARK
from digital_professor.retrieval.search import Retriever


def main():
    cases = load_jsonl(BENCHMARK / 'benchmark_50.jsonl')
    passages = {r['passage_id']: r for r in load_jsonl(DATA / 'passages.jsonl')}
    documents = {r['document_id']: r for r in load_jsonl(DATA / 'documents.jsonl')}
    manifest = json.loads((BENCHMARK / 'benchmark_manifest.json').read_text())
    digest = hashlib.sha256((BENCHMARK / 'benchmark_50.jsonl').read_bytes()).hexdigest()
    assert digest == manifest['dataset_sha256']
    assert hashlib.sha256((DATA / 'manifest.json').read_bytes()).hexdigest() == manifest['source_manifest_sha256']
    directory = HERE / 'refinement_runs'
    directory.mkdir(exist_ok=True)
    out = {'metadata': {'time_utc': datetime.now(timezone.utc).isoformat(), 'dataset_sha256': digest,
                       'source_sha256': manifest['source_manifest_sha256'],
                       'policy_version': '2', 'file_mode': 'soft', 'file_preference': 4,
                       'comparison_facet_rerank': '60% normalized fusion + 40% normalized character-ngram TF-IDF similarity',
                       'candidate_limit': 40, 'context_chars': 12000,
                       'limits': 'Same-set, post-hoc silver-label evaluation. No evidence labels enter search.'},
           'summaries': {}, 'cases': {}}
    baseline = None
    for name, decompose, top_k in [('full_6', False, 6), ('facets_6', True, 6), ('full_8', False, 8)]:
        start = time.perf_counter()
        with Retriever() as r:
            reports = r.search_many([case['question'] for case in cases], decompose_query=decompose, top_k=top_k)
            timings = r.last_encoding_timings
        scored = [score_case(case, report, passages, documents, {}) for case, report in zip(cases, reports)]
        summary = summarize(cases, scored, time.perf_counter()-start, timings, [])
        summary['top_k'], summary['decompose_query'] = top_k, decompose
        positives = [x for x in scored if x['kind']=='answerable']
        summary['complete_in_final_context'] = sum(all(rank is not None for rank in x['group_first_ranks']) for x in positives)/len(positives)
        if baseline is None:
            baseline = {x['id']: x for x in positives}
        summary['fixed_vs_full_6'] = [x['id'] for x in positives if x['complete_at']['6'] and not baseline[x['id']]['complete_at']['6']]
        summary['regressed_vs_full_6'] = [x['id'] for x in positives if not x['complete_at']['6'] and baseline[x['id']]['complete_at']['6']]
        summary['answerable_blocked'] = [c['id'] for c,r in zip(cases,reports) if c['kind']=='answerable' and r['status']!='found']
        summary['challenge_decisions'] = {c['id']:r['scope_assessment'] for c,r in zip(cases,reports) if c['kind']!='answerable'}
        out['summaries'][name],out['cases'][name] = summary, scored
        (directory/f'{name}.jsonl').write_text(''.join(json.dumps({'id':c['id'],'report':r})+'\n' for c,r in zip(cases,reports)))
        print(name, 'complete@6',summary['complete_at6'],'complete final',summary['complete_in_final_context'],
              'fixed',summary['fixed_vs_full_6'],'regressed',summary['regressed_vs_full_6'],flush=True)
    (HERE/'refinement_results.json').write_text(json.dumps(out,indent=2)+'\n')
    lines = ['# Retrieval refinement: scope contract and query coverage', '',
             'This is a post-hoc comparison on the frozen 50-question silver-label set, not independent-topic or answer-generation validation.', '',
             '| Configuration | Complete@6 | Complete in final context | Group recall@6 | Mean context characters | Regressions vs full-6 |',
             '| --- | ---: | ---: | ---: | ---: | --- |']
    for name, summary in out['summaries'].items():
        lines.append(f"| {name} | {summary['complete_at6']:.3f} | {summary['complete_in_final_context']:.3f} | "
                     f"{summary['group_recall_at6']:.3f} | {summary['mean_context_characters']} | "
                     f"{', '.join(summary['regressed_vs_full_6']) or 'none'} |")
    lines += ['', '## What changed', '',
              '- Scope policy distinguishes excluded scope, mixed/ambiguous scope, filter conflicts and missing source types. Explicit exclusions and background study are not treated as requested scopes.',
              '- Report 1.1 carries rule matches, reasons, requested/allowed scopes, source requirements and next actions. Found does not imply sufficient evidence. Blocked/clarification outputs carry no answer excerpts.',
              '- Explicit compare/contrast and theorem-plus-application questions produce up to two focused queries. Original top evidence and up to two results per facet compete within the existing top-6/budget limits. Comparison facets additionally blend character-ngram lexical relevance with fusion to preserve technical terms and word forms.',
              '- Fusion score is retained separately from selection score; query matches and selection reasons expose the new behavior.', '',
              '## Limits', '',
              'The remaining Q11/Q18 gold anchors had ranked seventh under full-query selection. Facet retrieval recovered both without reading labels at runtime. This does not verify textbook correctness or final answer quality. Rules do not identify every unsupported topic or every phrasing; instructors and new-topic holdouts are still needed. Extra facet queries incur additional embedding and database work.', '']
    (HERE/'refinement_report.md').write_text('\n'.join(lines))


if __name__=='__main__':
    main()
