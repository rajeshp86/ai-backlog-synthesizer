You will be given a list of draft user stories. Your task is to group them into epics (cohesive delivery themes) and break each story into 3-7 concrete implementation tasks that an engineering team could pick up directly.

# Stories (from the Story Writer Agent)

{{STORIES_JSON}}

# What to produce

Reply with a single JSON object of this exact shape:

{
  "epics": [
    {
      "id": "EP-01",
      "title": "Short epic title.",
      "description": "1-2 sentences describing the cohesive theme that links the stories under this epic.",
      "stories": [
        {
          "id": "ST-01",
          "title": "...",
          "description": "...",
          "user_story": "...",
          "acceptance_criteria": ["..."],
          "priority": "...",
          "priority_rationale": "...",
          "tags": ["..."],
          "source_topic_id": "...",
          "evidence": [
            {
              "topic_id": "T-01",
              "theme": "...",
              "raw_quote": "...",
              "speaker": "...",
              "sentiment": "..."
            }
          ],
          "potential_constraint_conflicts": ["..."],
          "tasks": [
            {
              "title": "Concrete implementation task.",
              "type": "backend | frontend | data | infra | qa | spike"
            }
          ]
        }
      ]
    }
  ]
}

# Field preservation requirements

- Preserve every input story field verbatim, copied through exactly as provided.
- The schema above shows the minimum required fields and the exact shape of the `evidence` block as it arrives in the input.
- If an input story contains additional fields beyond those listed above, copy them through unchanged.
- Add `tasks` as the only new field on each story.

# Rules

1. Every input story must appear under exactly one epic. No story may be omitted, duplicated, or left ungrouped.
2. Every input story `id` must appear exactly once in the output.
3. Group stories into epics based on a shared platform area, customer journey, engineering concern, or delivery theme. Epics must be meaningful cohesive themes, not buckets by priority, size, or arbitrary category.
4. Create the minimum number of epics that still preserves meaningful grouping. Do not create one epic per story unless the stories are genuinely unrelated.
5. Prefer the smallest cohesive grouping that could plausibly be tracked as one delivery initiative.
6. Preserve every input story field verbatim, including any additional fields present in the input. Do not rewrite, summarize, normalize, or re-shape any field — including `evidence`. Copy `evidence` through exactly as it appears in the input, with all of its sub-fields intact.
7. Audit-required fields must appear unchanged on every story if present in the input, especially:
   `id`, `priority_rationale`, `source_topic_id`, `evidence`, and `potential_constraint_conflicts`.
8. Generate 3-7 tasks per story.
9. Each task must be a concrete unit of engineering work that could be assigned to one team member and completed independently within normal sprint work.
10. Do not simply restate acceptance criteria as tasks. Tasks should represent the engineering work needed to satisfy the story.
11. Use only these task types:
    - `backend` for APIs, services, business logic, orchestration
    - `frontend` for UI, screens, client behavior
    - `data` for schema, migrations, persistence, data transformations
    - `infra` for environments, CI/CD, deployment, observability, configuration, permissions
    - `qa` for automated tests, regression coverage, validation, test case implementation
    - `spike` for research, investigation, prototyping, or technical discovery needed before implementation
12. Include a `spike` task only when uncertainty, technical risk, architectural ambiguity, or missing information clearly justifies investigation before implementation.
13. Do not remove, reinterpret, or resolve `potential_constraint_conflicts` when generating tasks. Preserve all conflict indicators exactly as provided.
14. If a story includes security, compliance, integration, or performance implications, include tasks that reflect the required engineering work where appropriate, but do not invent requirements not supported by the story.
15. Assign sequential epic ids in the form `EP-01`, `EP-02`, etc., in the order you emit the epics.
16. Return valid JSON only. No markdown fences, commentary, or preamble.
