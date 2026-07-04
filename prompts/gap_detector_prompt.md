You will be given:
1. A list of newly drafted user stories
2. For each new story, a shortlist of the most semantically similar existing JIRA or GitHub tickets
3. The architectural constraints the engineering team must respect

Duplicate detection is handled separately by a local embedding-based process. Your task is to identify only:
- Conflicts — new stories that contradict a `must` or `forbidden` architectural constraint
- Gaps — important capabilities clearly implied by the source material but not covered by either the new stories or the likely-matching existing backlog

# New stories

{{NEW_STORIES_JSON}}

# Candidate existing tickets per new story

{{CANDIDATES_JSON}}

# Architectural constraints

{{CONSTRAINTS_JSON}}

# What to produce

Reply with a single JSON object of this exact shape:

{
  "conflicts": [
    {
      "story_id": "ST-01",
      "with": "C-01",
      "severity": "high | medium | low",
      "reason": "One sentence explaining how the story contradicts the constraint."
    }
  ],
  "gaps": [
    {
      "id": "G-01",
      "title": "Short label for the missing capability.",
      "description": "1-2 sentences describing what is missing and why it matters.",
      "related_ids": ["ST-01"],
      "evidence": "One sentence — a direct quote or close paraphrase grounded in the source material — showing why this gap exists."
    }
  ]
}

# Rules for conflicts

1. Only flag conflicts against constraints whose severity is `must` or `forbidden`.
2. A conflict must be a real contradiction, bypass, weakening, or required exception relative to the constraint. Do not flag a story simply because it touches the same area.
3. Use the story's `potential_constraint_conflicts` field as a hint, but validate conflicts against the actual constraint statements.
4. Use `severity` to reflect how seriously the story undermines the constraint:
   - `high` = directly violates or depends on violating the constraint
   - `medium` = likely requires an exception, workaround, or reinterpretation
   - `low` = mild but plausible contradiction that needs reviewer attention
5. If a story proposes a capability that is clearly blocked by a `must` or `forbidden` constraint, preserve the conflict in the output rather than suppressing it.

# Rules for gaps

6. A gap is an important capability that the source evidence strongly implies should exist, but which is not adequately covered by:
   - the new stories, and
   - the likely-matching existing backlog candidates
7. Be conservative. Only report gaps that a real backlog reviewer would likely call out during grooming.
8. Do not invent gaps from general best practices or assumptions. Every gap must be supported by explicit or strongly implied evidence from the available source material.
9. Gaps should be capability-level omissions, not missing subtasks or acceptance criteria.
10. If a capability is partially addressed but a clearly distinct and important part is still missing, you may report that as a gap if the omission would matter to delivery or review.
11. Each gap must include at least one entry in `related_ids` (the ids of the new stories and/or existing candidate tickets this gap relates to) and a non-empty `evidence` sentence.
12. Assign sequential gap ids in the form `G-01`, `G-02`, etc., in the order you emit the gaps.

# General rules

13. Base your judgment only on the provided new stories, candidate tickets, and architectural constraints.
14. Candidate tickets are provided as context to help judge whether something is already covered in the backlog. Do not produce duplicates in this output — duplicate detection is handled elsewhere.
15. If the evidence is weak or ambiguous, prefer not to flag a conflict or gap. Empty `conflicts` and empty `gaps` lists are valid and expected when nothing qualifies.
16. Return valid JSON only. Do not include markdown fences, commentary, or preamble.
17. Keep all string values concise — `reason` and `evidence` must be one sentence each; `description` must be at most two sentences. Never exceed these limits.

# Worked example (illustrative — do not copy its content)

Given a story `ST-01` "Call the card processor directly from the PartnerPortal" and a `forbidden` constraint `C-02` "all payments must go through InvoiceGateway per PCI", a correct conflict is:

{ "story_id": "ST-01", "with": "C-02", "severity": "high",
  "reason": "The story calls the card processor directly, which directly violates the PCI requirement that all payments go through InvoiceGateway." }

A correct gap, when the discussion implies firmware stall events must be reconciled after a network outage but no story or backlog ticket covers it:

{ "id": "G-01", "title": "Firmware stall detection and recovery after WAN outage",
  "description": "Stories enable offline firmware deployment queuing during connectivity loss but none address detecting a stall and resuming normal operation once the plant network reconnects, which matters for deployment reliability.",
  "related_ids": ["ST-01"],
  "evidence": "The team described queuing firmware updates during WAN outages but never mentioned how stalls are detected or how normal operation resumes on reconnect." }
