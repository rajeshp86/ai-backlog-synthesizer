# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

**Backlog Synthesizer** is a multi-agent AI system that ingests heterogeneous inputs (meeting transcripts, architecture wikis, existing JIRA/GitHub backlogs, optional images) and produces a structured Epic → Story → Task hierarchy with gap detection, conflict detection, and duplicate detection. Every agent decision is recorded in a SHA-256-chained append-only audit log.

## Setup

Python 3.13 is required (pinned; 3.14+ lacks native-dep wheels).

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt   # use lock file, NOT requirements.txt
cp .env.example .env                    # edit with ANTHROPIC_API_KEY (required)
```

## Common Commands

```bash
make ui            # Start Streamlit UI at http://localhost:8502
make test          # pytest (all mocked, ~1s, no API credit)
make lint          # ruff lint check
make eval-fast     # Deterministic golden evaluation
make eval          # Full eval with LLM-as-judge (costs API credit)
make clean         # Remove caches and __pycache__
```

**Running individual tests:**
```bash
pytest tests/test_agents.py -v          # per-agent unit tests
pytest tests/test_orchestrator.py -v    # E2E pipeline (mocked Claude)
pytest tests/test_guardrails.py -v      # security checks
```

**Evaluation:**
```bash
python evaluation/run_evaluation.py --case case_07   # single golden case
python evaluation/ab_compare.py --prompt prompts/parser_prompt.md --variant prompts/experiments/parser_prompt_v2.md
```

## Architecture

### Data Flow

```
Streamlit UI → InputSanitizer (8 injection rules + PII) → budget/rate gates
    → LangGraph StateGraph (7 nodes) → synthesis.json + synthesis.md + audit_trail.md
    → optional: publish to JIRA / seed Confluence
```

### Entry Points

- `app.py` — Streamlit UI (3,100+ lines)
- `src/pipeline.py` — LangGraph `StateGraph`; this is the real orchestrator
- `src/orchestrator.py` — backward-compat wrapper over `pipeline.py`

### LangGraph Pipeline Nodes (in order)

| Node | Agent | What it does |
|---|---|---|
| `initialize_node` | — | Live-fetch Confluence/JIRA if requested; set up AuditLog + MemoryStore |
| `parse_node` | `DiscoveryEngine` | Extract topics, quotes, summary from transcript |
| `extract_constraints_node` | `PolicyEngineAgent` | Pull architecture rules and compliance constraints |
| `write_stories_node` | `StoryGenerationAgent` | Generate Given/When/Then user stories with AC and priority |
| `decompose_epics_node` | `DeliveryPlannerAgent` | Group stories into epics, decompose tasks |
| `detect_gaps_node` | `InsightScannerAgent` | Embedding-based duplicate detection + LLM conflict/gap reasoning |
| `finalize_node` | — | Guardrails check, OutputScanner, token tallying |

### Shared State

`src/memory/state.py` defines `PipelineState` — a 24-field TypedDict that flows through all LangGraph nodes. Agents read from it and write their outputs back to it.

### Memory Backends

`src/memory/store.py` (`MemoryStore`) provides a KV layer (agent handoff) and vector layer (semantic duplicate detection via sentence-transformers).

- Default: in-process numpy (no persistence)
- `MEMORY_PERSISTENT=1`: NPZ cache (single-host)
- `USE_CHROMADB=1`: ChromaDB (HA / multi-replica)

### Agent Design

Agents (`src/agents/`) all extend `Agent` (from `agents/base.py`) and accept a generic `tool=` kwarg, not hardcoded to Claude — this allows swapping Gemini without changing agent code. Prompts live in `prompts/*.md`, not inline.

| Agent class | File | Role |
|---|---|---|
| `DiscoveryEngine` | `discovery_engine.py` | Extracts topics and summary from transcript |
| `PolicyEngineAgent` | `policy_engine_agent.py` | Pulls architecture rules and compliance constraints |
| `StoryGenerationAgent` | `story_generation_agent.py` | Drafts Given/When/Then user stories |
| `DeliveryPlannerAgent` | `delivery_planner_agent.py` | Groups stories into epics, decomposes tasks |
| `InsightScannerAgent` | `insight_scanner_agent.py` | Embedding-based duplicate detection + LLM conflict/gap reasoning |

### Security Layer

`src/security.py` — `InputSanitizer` (8 injection pattern rules + PII + toxicity) runs before the pipeline. `OutputScanner` runs in `finalize_node`. Findings can alert to Slack/Teams/PagerDuty via `src/alerts.py`.

### Circuit Breaker

`src/circuit_breaker.py` — independent `CLAUDE_CB` and `GEMINI_CB` instances (CLOSED → OPEN → HALF_OPEN). Failure threshold: 5; recovery probe: 60s.

### Audit Log

`src/memory/audit_log.py` — append-only SQLite with SHA-256 hash chaining. Every agent decision is logged with PII redaction. Query with `scripts/audit_query.py`.

## Key Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required** |
| `GOOGLE_API_KEY` | — | For Gemini/Balanced presets |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` | Override default model |
| `JIRA_MODE` / `CONFLUENCE_MODE` | `mock` | Set to `live` for real Atlassian |
| `USE_CHROMADB=1` | — | Persistent vector store |
| `MEMORY_PERSISTENT=1` | — | NPZ embedding cache |
| `LOG_FORMAT` | `text` | Set to `json` for structured logging |
| `MAX_CONCURRENT_SYNTHESES` | `3` | Semaphore concurrency limit |

See `.env.example` for the full reference with comments.

## Evaluation Harness

`evaluation/` contains 10 hand-curated golden cases in `evaluation/golden_dataset/`. Deterministic metrics: completeness, tag F1, conflict/gap F1. Optional LLM-as-judge scores 5 qualitative dimensions. Results written to `evaluation/results/<timestamp>/`. `evaluation/dashboard.py` shows trend/regression analysis.

## Docker

```bash
docker build -t backlog-synthesizer:latest .
docker run -d -p 8502:8502 --env-file .env backlog-synthesizer:latest
```

The Dockerfile is multi-stage (Python 3.13, non-root user, pre-warms sentence-transformer). `entrypoint.sh` handles graceful SIGTERM shutdown by waiting for in-flight LLM stages.

## Operational Notes

- **Prometheus metrics** on port 9090 (`src/metrics.py`)
- **OpenTelemetry** via `OTEL_ENABLED=1` + `OTEL_EXPORTER_OTLP_ENDPOINT`
- **Runbook**: `docs/RUNBOOK.md` — covers injection alerts, circuit breaker, OOM, audit DB lock
- **Terraform (Azure)**: `infra/azure/` targets Azure Container Apps + Key Vault + ACR
- **Terraform (AWS)**: `infra/aws/` targets AWS free tier — EC2 t2.micro + ECR + S3 + Elastic IP. Run `terraform output -json all_github_secrets` after apply to get GitHub Actions secret values.
- **GitHub Actions**: `.github/workflows/cd-aws.yml` — build → ECR push → SSH deploy → smoke test (triggers on push to `main`). `.github/workflows/cd-azure.yml` — manual canary deploy to Azure.
- **JIRA publish**: Jira write-back is available via `JiraTool.publish_synthesis()`; use with care in live environments