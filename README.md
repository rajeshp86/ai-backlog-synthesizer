# Backlog Synthesizer

A multi-agent AI system that turns meeting transcripts, architecture wikis, and existing backlog tickets into a structured Epic → Story → Task hierarchy — with gap detection, conflict detection, duplicate detection, and a full audit trail.

---

## Running locally

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | **3.13 exactly** | 3.14+ lacks native-dep wheels; 3.12 and below untested |
| Anthropic API key | — | Required — get one at [console.anthropic.com](https://console.anthropic.com/) |
| Google API key | — | Optional — only needed for the **Open** and **Hybrid** model presets |

---

### Step 1 — Clone the repo

```bash
git clone https://github.com/rajeshp86/backlog-synthesizer.git
cd backlog-synthesizer
```

### Step 2 — Create a virtual environment

```bash
python3.13 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

### Step 3 — Install dependencies

Always use the lock file (not `requirements.txt`) to get exact pinned versions:

```bash
pip install -r requirements-lock.txt
```

### Step 4 — Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```env
ANTHROPIC_API_KEY=sk-ant-...       # required
GOOGLE_API_KEY=AIza...             # optional — enables Open / Hybrid presets
```

All other variables have sensible defaults for local development. See the [Configuration](#configuration) section for the full list.

### Step 5 — Start the app

```bash
make ui
# → http://localhost:8502
```

The UI opens in your browser. Upload a transcript, choose a model preset, and click **Run Synthesizer**.

---

### All available commands

```bash
make ui          # Start Streamlit UI at http://localhost:8502
make test        # Run the full test suite (mocked, offline, ~1s)
make lint        # Lint with ruff
make eval-fast   # Run golden evaluation — deterministic metrics only (no API cost)
make eval        # Run full evaluation with LLM-as-judge (spends API credit)
make clean       # Remove caches and __pycache__
```

---

### Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` on startup | Make sure you activated the venv (`source .venv/bin/activate`) and ran `pip install -r requirements-lock.txt` |
| `Configuration error: Missing required environment variable` | Check that `.env` exists and `ANTHROPIC_API_KEY` is set |
| Port 8502 already in use | Run `make ui` with a different port: `PORT=8503 streamlit run app.py --server.port 8503` |
| Slow first run (~30s) | The sentence-transformer model loads on first use — subsequent runs are instant |
| `Pipeline failed: ...` error in the UI | Check the audit trail tab for the full error. Most common cause is an invalid or expired API key |
| Open / Hybrid preset shows no output | `GOOGLE_API_KEY` is not set — add it to `.env` or switch to the **Elite** preset |

---

## What it does

Feed it any combination of:

- **Meeting transcripts** (`.txt`, `.md`, `.pdf`)
- **Architecture / wiki exports** describing constraints and platform limits (`.md`)
- **Existing backlog tickets** from JIRA or GitHub Issues (live API or mocked JSON)

Get back:

| Output | Description |
|---|---|
| **Epics** | High-level themes grouping related work |
| **Stories** | User stories with full Given/When/Then acceptance criteria |
| **Tasks** | Concrete implementation steps under each story |
| **Gaps** | Capabilities the requirements imply but the backlog hasn't planned |
| **Conflicts** | New requests that contradict architectural constraints |
| **Duplicates** | New requests that overlap with existing JIRA/GitHub items |
| **Audit trail** | Every agent decision, timestamped and SHA-256 chained |

---

## Architecture

Five specialized agents coordinate through a shared memory store. Every decision is recorded in an append-only audit log.

```
       ┌──────────────────────┐
       │     Orchestrator     │
       └──────────┬───────────┘
                  │
   ┌──────────────┼──────────────┬──────────────┬──────────────┐
   ▼              ▼              ▼              ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│  Discovery  │→│Policy Engine│→│    Story    │→│  Delivery   │→│  Insight    │
│   Engine    │ │    Agent    │ │  Generation │ │  Planner    │ │  Scanner    │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
                        │
              ┌─────────┴──────────┐
              │ Shared Memory +    │
              │ Audit Log          │
              └────────────────────┘
```

| Agent | Responsibility |
|---|---|
| **Discovery Engine** | Extracts topics, quotes, and summary from the transcript |
| **Policy Engine Agent** | Pulls architecture rules and compliance constraints |
| **Story Generation Agent** | Drafts Given/When/Then user stories with acceptance criteria |
| **Delivery Planner Agent** | Groups stories into epics and decomposes tasks |
| **Insight Scanner Agent** | Embedding-based duplicate detection + LLM conflict/gap reasoning |

See [architecture.md](architecture.md) for the full diagram and agent contracts.

---

## Configuration

All configuration lives in `.env`. Copy `.env.example` to get started — it has comments on every variable.

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | Your Anthropic API key |
| `GOOGLE_API_KEY` | No | Enables Gemini / Open and Hybrid presets |
| `ANTHROPIC_MODEL` | No | Override model (default: `claude-haiku-4-5`) |
| `JIRA_BASE_URL` | No | Live Jira base URL (e.g. `https://yourco.atlassian.net`) |
| `JIRA_EMAIL` | No | Atlassian account email |
| `JIRA_API_TOKEN` | No | Atlassian API token (covers both Jira and Confluence) |
| `JIRA_PROJECT_KEY` | No | Project key for live Jira fetch (e.g. `QT`) |
| `JIRA_MODE` | No | `mock` (default) or `live` |
| `CONFLUENCE_MODE` | No | `mock` (default) or `live` |
| `MEMORY_PERSISTENT=1` | No | Cache embeddings to disk between runs |
| `USE_CHROMADB=1` | No | Use ChromaDB instead of in-process numpy |
| `MAX_CONCURRENT_SYNTHESES` | No | Semaphore limit (default: `3`) |

---

## Optional capabilities

- **PDF transcripts** — pypdf parses text-extractable PDFs; upload directly via the UI.
- **Live Atlassian sources** — fill in the `JIRA_*` block in `.env`, then toggle Confluence/Jira in the sidebar and paste a Confluence page ID. No feature flag required.
- **Persistent vector memory** — set `MEMORY_PERSISTENT=1` to cache embeddings under `.cache/memory/` between runs.
- **Whiteboard images** — attach a PNG/JPG as additional source material (vision-capable models only).
- **Seed sample data into Confluence** — `python scripts/seed_confluence.py` uploads the bundled sample docs to your space.

---

## Running tests

```bash
make test          # full suite — all mocked, ~25s, no API credit
make lint          # ruff lint check
make eval-fast     # deterministic golden evaluation (no LLM judge)
make eval          # full evaluation with LLM-as-judge (spends API credit)
```

All tests are fully mocked — no API key needed.

---

## Model presets

Pick a preset in the sidebar **Models** panel:

| Preset | Models used | Cost per run |
|---|---|---|
| **Open** | All Gemini Flash (free tier) | ~$0 |
| **Hybrid** | Gemini Flash for extraction; Claude Haiku for Story Writer + Gap Detector | ~$0.01 |
| **Elite** | All Claude Haiku | ~$0.03 |

You can also override individual stages with the advanced selector.

---

## CI/CD & Infrastructure

### Application workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | Push / PR to `main` | Tests, lint, Docker build verification, optional eval suite |
| `cd-aws.yml` | Push to `main` | Build image → push to ECR → SSH deploy to EC2 → smoke test |
| `cd-azure.yml` | Manual (`workflow_dispatch`) | Canary deploy to Azure Container Apps |

### Infrastructure workflows (Terraform)

| Workflow | Trigger | What it does |
|---|---|---|
| `infra-aws.yml` | PR touching `infra/aws/**` | `terraform plan` — posts output as PR comment |
| | Push to `main` touching `infra/aws/**` | `terraform apply` (gated on `aws-production` environment approval) |
| | Manual dispatch | Choose `plan`, `apply`, or `destroy` |
| `infra-azure.yml` | PR touching `infra/azure/**` | `terraform plan` — posts output as PR comment |
| | Push to `main` touching `infra/azure/**` | `terraform apply` (gated on `azure-production` environment approval) |
| | Manual dispatch | Choose `plan`, `apply`, or `destroy` |

#### One-time setup

**GitHub Environments** (Settings → Environments):

- Create `aws-production` and `azure-production`
- Add required reviewers to gate `apply` and `destroy`

**GitHub Secrets** (Settings → Secrets → Actions):

| Secret | Workflow | Description |
|---|---|---|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | infra-aws | IAM user credentials |
| `AWS_REGION` | infra-aws | e.g. `us-east-1` |
| `TF_STATE_BUCKET` | infra-aws | S3 bucket for Terraform state |
| `TF_STATE_LOCK_TABLE` | infra-aws | DynamoDB table for state locking |
| `TF_VAR_KEY_PAIR_NAME` | infra-aws | EC2 key pair name (must exist in AWS) |
| `AZURE_CREDENTIALS` | infra-azure | JSON from `az ad sp create-for-rbac --sdk-auth` |
| `ARM_SUBSCRIPTION_ID` / `ARM_TENANT_ID` / `ARM_CLIENT_ID` / `ARM_CLIENT_SECRET` | infra-azure | Service principal credentials |
| `TF_STATE_STORAGE_ACCOUNT` / `TF_STATE_RESOURCE_GROUP` | infra-azure | Azure Blob storage for Terraform state |
| `TF_VAR_ACR_NAME` / `TF_VAR_KEY_VAULT_NAME` / `TF_VAR_STORAGE_ACCOUNT_NAME` | infra-azure | Globally unique Azure resource names |
| `TF_VAR_SPN_OBJECT_ID` | infra-azure | Object ID of the GitHub Actions service principal |
| `TF_VAR_ANTHROPIC_API_KEY` | infra-azure | Written to Key Vault at provision time |

Bootstrap the state backends once before the first `apply` — commands are in the comments at the top of each workflow file.

---

## Docker

```bash
docker build -t backlog-synthesizer:latest .
docker run -d -p 8502:8502 --env-file .env backlog-synthesizer:latest
# → http://localhost:8502
```

---

## Project structure

```
backlog-synthesizer/
├── app.py                           ← Streamlit UI entry point
├── .env.example                     ← copy to .env and fill in API keys
├── requirements-lock.txt            ← pinned, hash-verified dependencies (use this)
├── requirements.txt                 ← unpinned input (do not use directly)
├── Makefile                         ← ui / test / lint / eval / clean
├── src/
│   ├── pipeline.py                  ← LangGraph StateGraph (7 nodes)
│   ├── orchestrator.py              ← backward-compat wrapper over pipeline.py
│   ├── input_loader.py              ← reads txt / md / pdf / json
│   ├── output_formatter.py          ← renders epic/story/task hierarchy → json + md
│   ├── security.py                  ← InputSanitizer + OutputScanner
│   ├── agents/
│   │   ├── base.py                  ← Agent base class
│   │   ├── discovery_engine.py
│   │   ├── policy_engine_agent.py
│   │   ├── story_generation_agent.py
│   │   ├── delivery_planner_agent.py
│   │   └── insight_scanner_agent.py
│   ├── tools/
│   │   ├── claude_tool.py           ← Claude API client
│   │   ├── jira_tool.py             ← JIRA API (live + mocked)
│   │   └── confluence_tool.py       ← Confluence API (live + mocked)
│   └── memory/
│       ├── store.py                 ← shared KV + vector memory
│       └── audit_log.py             ← SHA-256-chained append-only log
├── prompts/                         ← agent prompt templates (markdown)
├── samples/                         ← bundled sample transcript, constraints, backlog
├── evaluation/                      ← 10 golden cases, metrics, LLM-as-judge, dashboard
├── tests/                           ← pytest suite (per-agent + E2E + guardrails)
├── infra/
│   ├── aws/                         ← Terraform: EC2 t2.micro + ECR + S3 + Elastic IP
│   └── azure/                       ← Terraform: Azure Container Apps + Key Vault + ACR
└── .github/workflows/
    ├── ci.yml                       ← tests, lint, docker build, eval suite
    ├── cd-aws.yml                   ← build → ECR push → SSH deploy → smoke test
    ├── cd-azure.yml                 ← manual canary deploy to Azure
    ├── infra-aws.yml                ← Terraform plan/apply/destroy for AWS
    └── infra-azure.yml              ← Terraform plan/apply/destroy for Azure
```

---

## License

MIT — use freely.
