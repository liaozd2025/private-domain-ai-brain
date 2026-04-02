# Autoresearch Changelog — data-analysis skill

## Experiment 0 — baseline

**Score:** 8/9 (88.9%)
**Change:** none (original skill)
**Reasoning:** establishing baseline
**Result:** E5 failed — out-of-scope scenario (sales ranking) was answered instead of refused. Agent said "this doesn't apply" but then provided the ranking anyway, defaulting to general assistant behavior.
**Failing outputs:** Scenario E (普通销售排名): agent gave ranking despite saying skill doesn't apply

---

## Experiment 1 — keep

**Score:** 9/9 (100%) on original 5 scenarios
**Change:** Added explicit refusal instruction to "When to Use" negative cases: "应直接回复'此问题超出门店经营诊断范围，无法处理'，不提供任何替代分析"
**Reasoning:** Without an explicit behavior instruction, agent defaults to being helpful (answering the question anyway). Adding the exact response string eliminates ambiguity.
**Result:** E5 now passes. Agent refuses out-of-scope cleanly with the exact phrase.
**Failing outputs:** none on original 5 scenarios

---

## Experiment 2 — keep

**Score:** 13/13 (100%) on extended 7-scenario suite
**Change:** Changed action plan requirement from "至少包含以下字段" (bulleted list) to explicit 7-column table template with example row
**Reasoning:** "至少包含以下字段" is too weak — agents sometimes generate simplified tables (e.g., 4 columns) when not explicitly shown the required structure. An example table row forces the correct format.
**Result:** Scenario G (derived 成交均价) now produces correct 7-column action plan. All other scenarios unaffected.
**Failing outputs before fix:** Scenario G action plan had: 行动项/负责人/完成时限/预期效果 (4 columns) instead of required 7.

---

## Experiment 3 — keep

**Score:** 16/16 (100%) on full 8-scenario suite
**Change:** Replaced "读取 references/store-diagnosis-rules.md" in Quick Reference with inline thresholds and combination diagnosis rules
**Reasoning:** Reference files may not be auto-loaded in all deployment environments. The agent was already getting thresholds right (from training data), but making them inline: (1) makes the skill self-contained, (2) creates an authoritative source that overrides any training data drift, (3) adds the critical combination diagnosis rules that previously existed only in external files.
**Result:** New scenario H (high traffic + low experience rate) correctly triggered combo rule "客流高+体验率低 → 接待过载" and used 3人/天 standard without reference files. All evals pass.
**Remaining failure patterns:** none identified on current test suite
