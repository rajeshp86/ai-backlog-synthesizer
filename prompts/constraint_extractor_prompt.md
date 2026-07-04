You will be given the body of an internal wiki or Confluence page from Quantum Technologies' Digital Operations platform team. Your task is to extract the architectural constraints that downstream story-writing must respect: required integrations, platform limits, performance budgets, security/compliance rules, data handling requirements, offline rules, and explicitly forbidden approaches.

# Input

<wiki>
{{WIKI_CONTENT}}
</wiki>

# What to produce

Reply with a single JSON object of this exact shape:

{
  "constraints": [
    {
      "id": "C-01",
      "severity": "must | should | forbidden",
      "category": "integration | performance | security | compliance | platform | data | offline | other",
      "statement": "A single concrete declarative sentence describing one constraint.",
      "source_excerpt": "A short direct quote from the wiki anchoring this constraint.",
      "applies_to": ["partner-portal", "firmware-updates", "ncr-capa", "quality", "supply-chain", "mes", "telemetry", "payments", "compliance", "security", "performance", "infrastructure", "sso", "analytics", "offline-mode", "accessibility", "*"]
    }
  ]
}

# Severity definitions

- must — non-negotiable. Stories that contradict this should be flagged as conflicts.
- should — strongly preferred default. Deviating requires explicit justification.
- forbidden — explicitly banned or disallowed. Stories that propose this are conflicts.

# Rules

1. Stay literal. Only extract constraints the wiki explicitly states. Do not infer unwritten platform rules or best practices.
2. Be specific. Extract concrete, testable requirements, thresholds, prohibitions, or required integrations.
3. Map mandatory wording like "must", "required", "shall", or "need to" to `must`.
4. Map recommended wording like "should", "recommended", "prefer", or "default" to `should`.
5. Map explicit bans such as "do not", "never", "not allowed", "prohibited", or equivalent wording to `forbidden`.
6. Split compound statements into separate constraints when they impose independently testable requirements or prohibitions.
7. Preserve conditional logic in the `statement` when the rule applies only in a certain context.
8. Rewrite each constraint into a concise, implementation-oriented sentence while preserving the original meaning.
9. Use the shortest direct excerpt that clearly anchors the constraint. Do not fabricate quotes or merge distant text into one excerpt.
10. Use `applies_to` narrowly with the listed surface tags. Use `*` only if the source clearly applies system-wide or no narrower scope is stated.
11. Deduplicate repeated constraints. If the same rule appears multiple times, emit one normalized constraint using the clearest excerpt.
12. Skip narrative, principles, aspirations, and background context unless they impose a concrete, testable requirement.
13. Assign sequential ids in the form `C-01`, `C-02`, etc., in the order you emit the constraints.
14. Return valid JSON only. No markdown fences, commentary, or preamble.
