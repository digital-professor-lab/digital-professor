# Week 3 检索打磨结果

日期：2026 年 10 月 1 日。原始 Week 3 和第一次修复的评估文件保留，本次另存运行记录。

## 范围与资料判断

此前只凭出现某些词就返回 Not found，可能误伤否定表达、背景描述和混合问题。现在把请求范围、检索过滤范围、资料类型分开处理：

- 明确要求当前排除的 Calculus II，或未确认的数论第二学期：not_found / out_of_scope。允许显式 opt-in，解释是范围排除，不是宣布材料不存在。
- 同时涉及允许与排除的范围：needs_clarification / mixed_scope。
- 问题中的课程与选中的课程过滤冲突：needs_clarification / filter_conflict。
- 只说第二学期、没有课程：needs_clarification / ambiguous_scope。
- 请求课堂原话/录音或个人成绩，而选中课程没有所需来源：not_found / source_unavailable。
- “不要用 Calculus II”“学过 Calculus II，但要问 Calculus I”不会仅因出现课程名被拒绝。
- 没有匹配结果与已有候选但字符预算装不下分别返回不同原因，避免把预算不足说成资料不存在。

报告 1.1 保留原始字段，增加 scope_assessment，记录 decision、category、reason_code、requested_scopes、allowed_scopes、required_source_types、available_source_types、matched_rules、next_action 和 explanation。停止或澄清时 results 为空、context 为空；运行契约检查这些状态的一致性。提供了正式 JSON Schema 文件。found 仅表示返回了材料，evidence_assessment 仍为 not_assessed，不虚构证据充分性或概率。

## 剩余两题与选择策略

Q11 要求找到极限定理及应用，Q18 要求比较离散与连续模型。完整问句的融合排序让另一部分必要证据处于第七位；继续放宽每文件上限无法突破最终六段限制。

当前保留每文件四段的软偏好，并加入通用多部分检索：识别明确的比较、定理与应用问句，生成最多两个不带标准答案的子查询；保留原问句最强结果及各子查询最多两段证据，再在六段和原字符预算内完成选择。比较类子查询还结合字符 n-gram TF-IDF 词项贴合度，处理技术词语、词形和连字符。融合分数、选择分数、选择原因和子查询命中分别记录。

对照结果：

| 方法 | 最终最多段数 | 完整证据 |
| --- | ---: | ---: |
| 单问句 + 软偏好 | 6 | 44/46 |
| 子问题覆盖 + 软偏好 | 6 | 46/46 |
| 单问句直接增加段数 | 8 | 46/46 |

新默认仍最多六段，补齐 Q11/Q18，无已成功题退步；范围/已知问题泄漏与来源完整性错误均为零。四个挑战问题均有明确停止原因，46 道可回答题无误拒绝。

## 验证与限制

13 项行为测试覆盖范围否定、背景、混合范围、过滤冲突、资料类型缺失、显式 opt-in、软偏好、预算与输出一致性。

另写六个改写问题，沿用两个已知案例的证据锚点。当前五个完整，一个极限定理应用问题仍不完整。这些是同主题措辞检查，不是独立领域测试。46/46 是当前银标证据覆盖，不是回答正确率、教材正确率或学习效果。范围规则也不能识别所有隐含超范围或证据不足的问题。子查询增加本地嵌入与搜索工作；来源仍需教师审核。

## 证据文件

- ../week3/knowledge_base/retrieval/refinement_report.md
- ../week3/knowledge_base/retrieval/refinement_results.json
- ../week3/knowledge_base/retrieval/refinement_runs/
- ../week3/knowledge_base/retrieval/paraphrase_validation.json
- ../week3/knowledge_base/retrieval/retrieval_report.schema.json
