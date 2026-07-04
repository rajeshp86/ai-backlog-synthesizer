# Sample inputs

These files describe a single fictional product — **Quantum Technologies (QT) Manufacturing Platform**, a digital operations platform powering a global OEM electronics manufacturer serving enterprise clients across aerospace, defense, and industrial automation — across the three input types the Backlog Synthesizer accepts.

The four source documents and two ticket exports cross-reference each other so the agents have genuine overlaps, conflicts, and gaps to find. A reviewer can verify the synthesis is correct by spot-checking these intentional flags.

## The Quantum Technologies fiction in one paragraph

Quantum Technologies is a fictional OEM electronics manufacturer supplying precision control modules, industrial sensor assemblies, and embedded systems to ~200 enterprise OEM clients across aerospace, defense, and industrial automation. Their digital platform supports firmware deployments to ~40,000 embedded control modules in the field, a client-facing PartnerPortal for order placement and quality documentation, an NCR/CAPA quality management system (**QualityHub**, the system of record for all non-conformance and corrective action cases), a supplier collaboration portal (**SupplySync**) for ~500 active suppliers, and legacy Gen1 embedded controller hardware in 2019–2021 vintage that cannot receive differential firmware updates.

## The files

| File | What it is | Notable details |
|---|---|---|
| `meeting_notes.txt` | Digital Operations Q3 planning meeting transcript | Seven themes raised; one (remote firmware scripting by clients) explicitly declined; cross-references the architectural constraints in `architecture_constraints.md` and several existing JIRA tickets |
| `architecture_constraints.md` | Engineering architecture wiki page | Performance budgets, required integrations (IdentityVault, InvoiceGateway, QualityHub), security rules (IEC 62443, ITAR/EAR, AS9100, REACH/RoHS, GDPR/CCPA), offline tolerance per hardware tier, and forbidden patterns |
| `product_strategy.md` | Q3 strategy document from the VP of Digital Operations | Same themes as the meeting notes but formal; tags P0 vs P1; explicitly excludes remote firmware scripting, SupplySync portal redesign, B2B analytics dashboard |
| `jira_backlog.json` | 30 existing JIRA tickets | Multiple intentional overlaps with the meeting notes (QT-412 order status badge, QT-419 legacy ERP integration, QT-227 Kafka migration). Triggers RAG path (≥20 items). |
| `github_issues.json` | 13 existing GitHub issues | A second source of existing work; some overlap with JIRA, some unique (e.g., #142 remote diagnostic command reliability) |

## Intentional flags the agents should find

When the synthesiser runs against these inputs together, here is what a correct run should produce:

### Duplicates (new story ↔ existing ticket)

| Topic from meeting notes | Should be flagged as duplicate of | Confidence |
|---|---|---|
| PartnerPortal shows stale order status badge | `QT-412` (in-progress) + GitHub `#127` | High |
| Supplier delivery confirmation confusion | `QT-389` (supplier confirmation email) + GitHub `#121` | Medium-to-high |
| Remote diagnostic command dispatched without true acknowledgement | GitHub `#142` | High |

### Conflicts (story ↔ architecture constraint)

| Story idea | Conflicts with constraint | Severity |
|---|---|---|
| "Auto-rollback security-critical firmware updates" — anyone proposing this | "Automatic rollback of security-critical firmware updates is FORBIDDEN without a validated rollback image" (Section 3, IEC 62443) | High |
| "Show differential order status to different users based on contract tier" | "ITAR-controlled article orders require access control gating — no differential status without verified clearance" (Section 3) | Medium |
| "Use Gen1 controller background download for large firmware builds" | "Gen1 background firmware downloads cannot run more than 60 minutes without operator acknowledgement" (Section 4) | High if it doesn't gate by hardware |

### Gaps (implied but missing from both new stories and existing backlog)

The agents should also surface things the strategy/transcript *implies* but neither the new stories nor existing tickets cover. Examples a reviewer should expect:

- **Client consent capture flow for NCR detail notifications** (the strategy mentions consent-based NCR notifications but no story addresses *how* the client opts in)
- **Firmware stall detection and recovery heuristics** (offline resilience is mentioned but the *trigger* for declaring a stall and resuming normal operation isn't designed)
- **The NCR/CAPA audit log retention extension** (existing QT-321 covers this — so this is actually NOT a gap; the agent should recognise it's covered)

## Sample sizes and threshold behaviour

- `jira_backlog.json` has **30 tickets**, which is above the `RETRIEVAL_THRESHOLD=20` in `src/memory/store.py`. This triggers the embedding-based semantic search path.
- `github_issues.json` has 13 issues, so they're included in the LLM prompt directly without retrieval narrowing.

## How each sample is designed to be used

```bash
# Full run with all three sources:
python src/main.py \
    --transcript samples/meeting_notes.txt \
    --constraints samples/architecture_constraints.md \
    --backlog samples/jira_backlog.json

# Strategy document instead of meeting notes:
python src/main.py \
    --transcript samples/product_strategy.md \
    --constraints samples/architecture_constraints.md \
    --backlog samples/jira_backlog.json

# Smaller demo with no wiki:
python src/main.py --transcript samples/meeting_notes.txt
```