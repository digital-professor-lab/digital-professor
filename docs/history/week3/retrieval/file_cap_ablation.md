# Post-Hoc File-Cap Ablation

This is a diagnostic experiment on the same frozen version-2 questions. It was designed after inspecting the primary benchmark failures and is **not** part of the predeclared five-arm comparison.

Only the maximum number of selected passages per source file changed from 2 to 4; top-k remained 6 and the raw-excerpt budget remained 12,000 characters.

- Complete evidence@6: 0.870 -> 0.957.
- Required-group recall@6: 0.920 -> 0.973.
- Newly completed questions: Q02, Q16, Q43, Q46.
- Regressed questions: none.
- Mean assembled context characters: 10284 -> 9668.
- Alternative scope/issue leaks: 0; source integrity failures: 0.

A larger context and more passages from one document can increase noise and cost. This result does not justify changing the production default without instructor relevance judgments and answer-level evaluation.
