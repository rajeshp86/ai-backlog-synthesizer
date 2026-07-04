You will be given a list of topics extracted from a meeting transcript, plus a list of architectural constraints the engineering team must respect. Your task is to draft well-formed user stories that address each topic, while identifying where a draft may conflict with one or more constraints.

# Topics (from the Parser Agent)

{{TOPICS_JSON}}

# Architectural constraints (from the Constraint Extractor Agent)

{{CONSTRAINTS_JSON}}

# What to produce

Reply with a single JSON object of this exact shape:

{
  "stories": [
    {
      "id": "ST-01",
      "title": "Short backlog-style title describing the capability.",
      "description": "1-3 sentences in plain language, including caveats, ambiguity, supporting context, or any potential conflict with constraints.",
      "user_story": "As a <persona>, I want <capability>, so that <benefit>.",
      "acceptance_criteria": [
        "Given <context>, when <action>, then <observable outcome>."
      ],
      "priority": "High | Medium | Low",
      "priority_rationale": "A concrete non-empty sentence explaining the priority based on customer impact, revenue, compliance, release dependency, support load, operational risk, or similar evidence.",
      "tags": ["telemetry", "offline-mode"],
      "source_topic_id": "T-01",
      "potential_constraint_conflicts": ["C-01"]
    }
  ]
}

# Field definitions

- `id`: A unique story identifier in the form `ST-01`, `ST-02`, etc.
- `title`: A concise backlog-style title describing the capability to be delivered.
- `description`: Plain-language explanation of the story, including ambiguity, caveats, supporting context, and any conflict with constraints.
- `user_story`: Standard user story format: `As a <persona>, I want <capability>, so that <benefit>.`
- `acceptance_criteria`: 2-5 testable, externally observable acceptance criteria in Given/When/Then form.
- `priority`: `High`, `Medium`, or `Low`.
- `priority_rationale`: Required. A concrete explanation for why the story has this priority.
- `tags`: Use canonical Quantum Technologies tags whenever applicable.
- `source_topic_id`: The id of the topic from the Parser output that this story addresses. This must exactly match an `id` field in the topics input above (e.g. `"T-01"`, `"T-02"`). **Never use `"..."`, `"null"`, `""`, or any placeholder.** If you are unsure which topic a story addresses, pick the closest one by theme.
- `potential_constraint_conflicts`: Array of relevant constraint ids if this story may contradict a `must` or `forbidden` constraint; otherwise `[]`.

Note: you do **not** produce an `evidence` field. An evidence block is attached automatically by the system from the topic you cite in `source_topic_id`, so it can never be fabricated. Your only responsibility for traceability is to set `source_topic_id` accurately to the topic the story actually came from.

# Rules

1. Draft at least one story for every topic in the input. If the topic list is non-empty, the story list must also be non-empty.
2. Every topic `id` in the input must appear at least once as a `source_topic_id` in the output. Copy the exact `id` string from the topic — never invent a new one or use a placeholder like `"..."`.
2a. `source_topic_id` must be one of the exact `id` values from the topics list. Valid examples: `"T-01"`, `"T-02"`. Invalid: `"..."`, `null`, `""`, `"T-XX"`.
3. Never suppress a story because it conflicts with a constraint. If a requested capability appears blocked by a `must` or `forbidden` constraint, you must still draft the story, include the relevant constraint id in `potential_constraint_conflicts`, and explicitly mention the conflict in `description`.
4. Default to one story per topic. Produce two stories only when a topic clearly contains two separable user needs that would be implemented and prioritized independently. Never produce more than two stories for a single topic.
5. If a topic is ambiguous or underspecified, still draft the most reasonable story grounded in the topic summary. Explicitly call out uncertainty or missing detail in `description`. Do not invent specific facts, metrics, personas, workflows, or system behavior that are not supported by the input.
6. Choose the most plausible persona grounded in the topic. If no persona is explicitly stated, infer the narrowest reasonable persona from the topic and tags.
7. Acceptance criteria must be testable, externally observable, and written in Given/When/Then form. Provide 2-5 acceptance criteria per story. Avoid vague outcomes and avoid implementation details unless the topic or a constraint explicitly requires them.
8. `priority_rationale` must always be a concrete, non-empty sentence. Empty strings, "TBD", or vague phrases like "important" are not allowed.
9. Use these priority definitions:
   - `High` = blocks OEM client operations, production delivery, firmware deployments, compliance obligations, a revenue-critical flow, or a committed release
   - `Medium` = valuable and meaningful, but not currently blocking
   - `Low` = polish, convenience, or lower-impact improvement
10. Tags should use the canonical Quantum Technologies set whenever applicable:
   `partner-portal`, `firmware-updates`, `ncr-capa`, `quality`, `supply-chain`, `mes`, `telemetry`, `payments`, `compliance`, `security`, `performance`, `infrastructure`, `sso`, `analytics`, `offline-mode`, `accessibility`
   Add new tags only when none of these fit.
11. Mark a constraint in `potential_constraint_conflicts` only when the drafted capability plausibly contradicts, bypasses, weakens, or would require an exception to that constraint.
12. Assign sequential ids in the form `ST-01`, `ST-02`, etc., in the order you emit the stories.
13. If the topic list is empty (`[]`), and only then, return:
   {"stories": []}
14. Return valid JSON only. Do not include markdown fences, commentary, or preamble.

# Worked example (illustrative — do not copy its content)

Suppose the topics are three requested-but-blocked capabilities, and the constraints include `C-02` (forbidden: all invoice payments must go through InvoiceGateway — direct calls to card processors are not allowed, per PCI).

Correct output: **three stories**, one per topic, each with the relevant constraint id in `potential_constraint_conflicts` and the conflict called out in `description` — for example:

{
  "stories": [
    {
      "id": "ST-01",
      "title": "Call the card processor directly from the PartnerPortal",
      "description": "The PartnerPortal team requested calling the card processor directly to shave a hop off invoice payment. This conflicts with C-02 (PCI — all payments must go through InvoiceGateway); drafted so the conflict is visible to reviewers rather than dropped.",
      "user_story": "As an OEM client account admin, I want faster invoice payment checkout, so that settling my manufacturing orders is quick.",
      "acceptance_criteria": [
        "Given an invoice payment, when payment is initiated, then it is authorized within PCI rules or the system clearly explains why it cannot.",
        "Given a completed payment, when the receipt is issued, then it is reconciled exactly once with an audit record."
      ],
      "priority": "High",
      "priority_rationale": "The PartnerPortal team reports invoice payment friction and wants a faster path.",
      "tags": ["partner-portal", "payments", "compliance"],
      "source_topic_id": "T-01",
      "potential_constraint_conflicts": ["C-02"]
    }
  ]
}

INCORRECT output for that input: returning zero stories, or omitting the blocked asks. A blocked request is still a story — the conflict is surfaced downstream, not suppressed here.
