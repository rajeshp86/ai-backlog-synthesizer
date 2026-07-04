"""Generate architecture_diagram.png for the Backlog Synthesizer.

Run from the repo root:
    python generate_architecture_diagram.py

Requires: matplotlib (already in requirements.txt)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# ── Colour palette ────────────────────────────────────────────────────────────
BG       = "#0d1117"
PANEL_BG = "#161b22"
BORDER   = "#30363d"

C_AGENT    = "#1f3a5f"
C_TOOL     = "#3a2f1f"
C_SECURITY = "#3a1f2f"
C_INFRA    = "#1f3a2f"
C_AUTH     = "#2f1f3a"
C_LLM      = "#1a3a1f"
C_MEMORY   = "#3a3a1f"

T_PRIMARY = "#e6edf3"
T_MUTED   = "#8b949e"
T_ACCENT  = "#58a6ff"
T_GREEN   = "#3fb950"
T_AMBER   = "#d29922"
T_ROSE    = "#f85149"
T_VIOLET  = "#bc8cff"
T_SILVER  = "#c0c0c0"

ARROW     = "#58a6ff"
ARROW_ALT = "#3fb950"


def box(ax, x, y, w, h, color, border_color=BORDER, radius=0.015):
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=color, edgecolor=border_color,
        linewidth=0.8, alpha=0.92, zorder=3,
    )
    ax.add_patch(rect)


def label(ax, x, y, text, size=7, color=T_PRIMARY, weight="normal",
          ha="center", va="center", zorder=5):
    ax.text(x, y, text, fontsize=size, color=color, fontweight=weight,
            ha=ha, va=va, zorder=zorder)


def arrow(ax, x1, y1, x2, y2, color=ARROW, lw=0.9):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=color, lw=lw), zorder=4)


def section_header(ax, x, y, w, text, color=T_MUTED):
    label(ax, x + w / 2, y, text, size=6.5, color=color, weight="bold")


# ── Canvas ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(22, 14))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")

# Title
ax.text(0.5, 0.977, "Backlog Synthesizer — Architecture",
        fontsize=14, color=T_PRIMARY, fontweight="bold", ha="center", va="top", zorder=10)
ax.text(0.5, 0.962,
        "Multi-agent AI System  ·  LangGraph Orchestration  ·  AWS (EC2 + ECR)  ·  Azure Container Apps",
        fontsize=7.5, color=T_MUTED, ha="center", va="top", zorder=10)

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 1 — Inputs  |  Auth  |  LLM Providers
# ═══════════════════════════════════════════════════════════════════════════════
box(ax, 0.01, 0.840, 0.98, 0.110, PANEL_BG, border_color="#444c56")
section_header(ax, 0.01, 0.958, 0.98,
               "INPUTS  ·  LLM PROVIDERS", color=T_MUTED)

# Inputs
for i, (name, sub) in enumerate([
    ("Transcript", ".txt / .md / .pdf"),
    ("Vision", "Whiteboard / PNG"),
    ("Confluence", "Live page REST"),
    ("Jira", "Live REST / fixture"),
]):
    xi = 0.02 + i * 0.075
    box(ax, xi, 0.852, 0.068, 0.075, C_TOOL)
    label(ax, xi + 0.034, 0.897, name, size=6.5, color=T_AMBER, weight="bold")
    label(ax, xi + 0.034, 0.880, sub, size=5.5, color=T_MUTED)

# No-auth notice
box(ax, 0.330, 0.848, 0.270, 0.082, "#1a1f2e", border_color="#444c56")
label(ax, 0.465, 0.910, "NO AUTHENTICATION  ·  AUTH_DISABLED=1", size=6.5, color=T_SILVER, weight="bold")
label(ax, 0.465, 0.893, "Local / internal use — no login wall", size=6, color=T_MUTED)
label(ax, 0.465, 0.876, "Pre-run gates: rate limit · budget · idempotency · semaphore", size=5.8, color=T_MUTED)
label(ax, 0.465, 0.860, "InputSanitizer runs before every pipeline invocation", size=5.8, color=T_MUTED)

# LLM Providers
for i, (name, api, note, col) in enumerate([
    ("Claude Sonnet 4.5", "Anthropic API", "prompt cache ≥4KB", T_GREEN),
    ("Gemini 2.5 Flash",  "Google AI API", "GOOGLE_API_KEY", T_AMBER),
]):
    xi = 0.615 + i * 0.122
    box(ax, xi, 0.852, 0.115, 0.075, C_LLM)
    label(ax, xi + 0.0575, 0.900, name, size=6.5, color=col, weight="bold")
    label(ax, xi + 0.0575, 0.884, api, size=5.5, color=T_MUTED)
    label(ax, xi + 0.0575, 0.869, note, size=5.5, color=col)

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 2 — LangGraph Pipeline
# ═══════════════════════════════════════════════════════════════════════════════
box(ax, 0.01, 0.630, 0.98, 0.195, PANEL_BG, border_color="#444c56")
section_header(ax, 0.01, 0.833,  0.98,
               "LANGGRAPH PIPELINE  ·  StateGraph  ·  Parallel fan-out stages 0+1  ·  PipelineState TypedDict",
               color=T_ACCENT)

# initialize node
box(ax, 0.018, 0.752, 0.088, 0.060, C_AGENT, border_color=T_ACCENT)
label(ax, 0.062, 0.792, "initialize", size=7.5, color=T_ACCENT, weight="bold")
label(ax, 0.062, 0.776, "fetch Jira / Confluence", size=5.5, color=T_MUTED)
label(ax, 0.062, 0.764, "injection scan", size=5.5, color=T_ROSE)
label(ax, 0.062, 0.752, "index tickets (embeddings)", size=5.2, color=T_MUTED)

arrow(ax, 0.106, 0.784, 0.148, 0.800, color=ARROW)
arrow(ax, 0.106, 0.782, 0.148, 0.762, color=ARROW)

ax.text(0.128, 0.812, "parallel", fontsize=5.2, color=T_GREEN, ha="center",
        bbox=dict(boxstyle="round,pad=0.15", facecolor="#0d2b0d", edgecolor=T_GREEN, lw=0.6))
ax.text(0.128, 0.755, "barrier →", fontsize=5.2, color=T_AMBER, ha="center",
        bbox=dict(boxstyle="round,pad=0.15", facecolor="#2b1a00", edgecolor=T_AMBER, lw=0.6))

# 5 agent nodes
agents = [
    (0.148, 0.778, 0.118, 0.048, "① Discovery Engine",
     "gemini-flash / claude-haiku",  "topics[] + summary", T_ACCENT),
    (0.148, 0.726, 0.118, 0.048, "② Policy Engine Agent",
     "gemini-flash / claude-haiku",  "constraints[]",      T_ACCENT),
    (0.310, 0.748, 0.130, 0.048, "③ Story Generation Agent",
     "claude-haiku  (reasoning-heavy)", "stories[] + evidence[]", T_AMBER),
    (0.495, 0.748, 0.130, 0.048, "④ Delivery Planner Agent",
     "gemini-flash / claude-haiku",  "epics[] with tasks[]", T_ACCENT),
    (0.682, 0.748, 0.148, 0.048, "⑤ Insight Scanner Agent",
     "claude-haiku  max_tokens=8000 ✓", "duplicates[] conflicts[] gaps[]", T_ROSE),
]
for x, y, w, h, name, model, out, tc in agents:
    box(ax, x, y, w, h, C_AGENT, border_color=tc)
    label(ax, x + w / 2, y + h - 0.010, name,  size=7, color=T_PRIMARY, weight="bold")
    label(ax, x + w / 2, y + h - 0.023, model, size=5.5, color=T_MUTED)
    label(ax, x + w / 2, y + 0.008, f"→ {out}", size=5.5, color=tc)

# join / sequential arrows
arrow(ax, 0.266, 0.802, 0.310, 0.778, color=ARROW_ALT)
arrow(ax, 0.266, 0.750, 0.310, 0.768, color=ARROW_ALT)
arrow(ax, 0.440, 0.772, 0.495, 0.772, color=ARROW)
arrow(ax, 0.625, 0.772, 0.682, 0.772, color=ARROW)

# finalize node
box(ax, 0.845, 0.750, 0.090, 0.048, C_MEMORY, border_color=T_AMBER)
label(ax, 0.890, 0.782, "finalize", size=7, color=T_AMBER, weight="bold")
label(ax, 0.890, 0.768, "guardrails check", size=5.5, color=T_MUTED)
label(ax, 0.890, 0.756, "audit fingerprint", size=5.5, color=T_MUTED)
arrow(ax, 0.830, 0.772, 0.845, 0.772, color=ARROW)

label(ax, 0.5, 0.640,
      "PipelineState TypedDict — topics | constraints | stories | epics | gaps | conflicts | duplicates | token_usage | stage_errors",
      size=5.8, color=T_MUTED)

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 3 — Tools · Security · Memory · Observability
# ═══════════════════════════════════════════════════════════════════════════════
box(ax, 0.01, 0.415, 0.98, 0.200, PANEL_BG, border_color="#444c56")
section_header(ax, 0.01, 0.623, 0.98,
               "TOOLS  ·  SECURITY  ·  MEMORY  ·  OBSERVABILITY", color=T_MUTED)

# Tools
box(ax, 0.018, 0.425, 0.295, 0.185, "#0d1117", border_color=BORDER)
label(ax, 0.165, 0.613, "TOOLS", size=6, color=T_AMBER, weight="bold")
tools = [
    ("JiraTool",       "list_all()  ·  publish_synthesis() Epic→Story→Sub-task", T_AMBER),
    ("ConfluenceTool", "get_page(id) REST  ·  BS4 HTML strip  −60% tokens",      T_AMBER),
    ("EmbeddingTool",  "all-MiniLM-L6-v2  ·  cosine≥0.6  ·  top-K=5 candidates",T_SILVER),
    ("ClaudeTool",     "ChatAnthropic  ·  prompt cache ≥4KB  ·  vision support",  T_GREEN),
    ("GeminiTool",     "ChatGoogleGenerativeAI  ·  GOOGLE_API_KEY",        T_AMBER),
]
for i, (name, desc, col) in enumerate(tools):
    yi = 0.597 - i * 0.028
    box(ax, 0.025, yi - 0.020, 0.281, 0.024, C_TOOL)
    label(ax, 0.035, yi - 0.007, name, size=6, color=col, weight="bold", ha="left")
    label(ax, 0.130, yi - 0.007, desc, size=5.2, color=T_MUTED, ha="left")

# Security
box(ax, 0.325, 0.425, 0.250, 0.185, "#0d1117", border_color=BORDER)
label(ax, 0.450, 0.613, "SECURITY", size=6, color=T_ROSE, weight="bold")
security = [
    ("InputSanitizer",   "8 injection patterns  ·  replace → [INJECTION REDACTED]"),
    ("OutputScanner",    "PII  ·  toxicity  ·  demographic bias"),
    ("Guardrails",       "AC count + GWT grammar  ·  duplicate titles  ·  weak priority rationale"),
    ("HMAC State", "token=raw.ts.HMAC(CLIENT_SECRET)  stateless CSRF"),
    ("JWT RS256",        "PyJWKClient JWKS verify  ·  1h cache  ·  valid_issuers"),
    ("Budget Store",     "try_reserve()  ·  settle_reservation()  ·  daily cap USD"),
]
for i, (name, desc) in enumerate(security):
    yi = 0.597 - i * 0.028
    box(ax, 0.332, yi - 0.020, 0.236, 0.024, C_SECURITY)
    col = T_GREEN if "NEW" in name else T_ROSE
    label(ax, 0.342, yi - 0.007, name, size=6, color=col, weight="bold", ha="left")
    label(ax, 0.342, yi - 0.017, desc, size=5.2, color=T_MUTED, ha="left")

# Memory / Audit / Observability
box(ax, 0.588, 0.425, 0.395, 0.185, "#0d1117", border_color=BORDER)
label(ax, 0.785, 0.613, "MEMORY  ·  AUDIT  ·  OBSERVABILITY", size=6, color=T_AMBER, weight="bold")
memory = [
    ("MemoryStore KV",    "put()/get() explicit agent handoff  ·  per-run isolated",       C_MEMORY, T_AMBER),
    ("MemoryStore Vector","in-process numpy | NPZ file | ChromaDB (USE_CHROMADB=1)",       C_MEMORY, T_AMBER),
    ("AuditLog",          "chain-fingerprint SHA-256  ·  every LLM call  ·  collapsible", C_MEMORY, T_AMBER),
    ("Prometheus :9090",  "syntheses_total  ·  synthesis_cost_usd  ·  tokens_total  ·  llm_errors_total",    C_INFRA,  T_GREEN),
    ("OpenTelemetry",     "pipeline.run  ·  node spans  ·  llm.call spans  ·  OTLP",      C_INFRA,  T_GREEN),
    ("Run History",       "RUNS_DIR/.runs/<user>/<ts>.json  ·  filter by date/model",     C_MEMORY, T_SILVER),
]
for i, (name, desc, col, tc) in enumerate(memory):
    yi = 0.597 - i * 0.028
    box(ax, 0.595, yi - 0.020, 0.381, 0.024, col)
    label(ax, 0.605, yi - 0.007, name, size=6, color=tc, weight="bold", ha="left")
    label(ax, 0.730, yi - 0.007, desc, size=5.2, color=T_MUTED, ha="left")

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 4 — Azure Deployment
# ═══════════════════════════════════════════════════════════════════════════════
box(ax, 0.01, 0.195, 0.98, 0.205, PANEL_BG, border_color="#444c56")
section_header(ax, 0.01, 0.408, 0.98,
               "AZURE DEPLOYMENT  ·  GitHub Actions CI/CD  ·  rg-quantumshield-entertainment / eastus",
               color=T_GREEN)

# CI/CD jobs
box(ax, 0.018, 0.205, 0.320, 0.192, "#0d1117", border_color=BORDER)
label(ax, 0.178, 0.400, "GITHUB ACTIONS  ·  infra-and-deploy.yml", size=6, color=T_GREEN, weight="bold")
jobs = [
    ("provision",          "az group/acr/cae/containerapp create — idempotent  ·  set -euo pipefail", T_GREEN),
    ("build",              "docker/build-push-action@v6  ·  :sha + :latest  ·  GHA layer cache",      T_ACCENT),
    ("deploy-staging",     "secret set  ·  registry set  ·  containerapp update",                     T_AMBER),
    ("  ENTRA_REDIRECT_URI","→ read Azure FQDN dynamically",                                   T_VIOLET),
    ("  GOOGLE_API_KEY",   "secretref:google-api-key",                                         T_AMBER),
    ("  ANTHROPIC_API_KEY","secretref:anthropic-api-key",                                              T_GREEN),
    ("  health check",     "/_stcore/health  ·  24×10s  ·  4min timeout",                            T_MUTED),
    ("deploy-production",  "environment: azure-production  ·  manual approval  ·  --revision-suffix", T_ROSE),
]
for i, (name, desc, col) in enumerate(jobs):
    yi = 0.385 - i * 0.023
    indented = name.startswith("  ")
    box(ax, 0.025, yi - 0.016, 0.305, 0.020, C_INFRA if not indented else "#0d1117",
        border_color=col if not indented else "#333")
    label(ax, 0.035 + (0.02 if indented else 0), yi - 0.006,
          name.strip(), size=6, color=col, weight="bold", ha="left")
    label(ax, 0.135, yi - 0.006, desc, size=5.2, color=T_MUTED, ha="left")

# Azure resources
box(ax, 0.352, 0.205, 0.330, 0.192, "#0d1117", border_color=BORDER)
label(ax, 0.517, 0.400, "AZURE RESOURCES", size=6, color=T_GREEN, weight="bold")
resources = [
    ("quantumshieldentacr0452.azurecr.io", "Container Registry  ·  Basic SKU  ·  admin enabled",       T_SILVER),
    ("cae-quantumshield-entertainment",  "Container Apps Environment  ·  eastus",                    T_GREEN),
    ("backlog-synthesizer-staging",      "min=0 max=1  ·  scale-to-zero  ·  port 8502",             T_AMBER),
    ("backlog-synthesizer-prod",         "min=1 max=3  ·  --revision-suffix rollback",               T_GREEN),
    ("sp-backlog-synthesizer-github",    "Contributor@subscription  ·  AcrPush role",                T_MUTED),
    ("rg-tfstate / tfstate-bucket",         "Terraform state  ·  infra/azure/ + infra/aws/",            T_MUTED),
]
for i, (name, desc, col) in enumerate(resources):
    yi = 0.385 - i * 0.028
    box(ax, 0.359, yi - 0.020, 0.316, 0.025, C_INFRA)
    label(ax, 0.369, yi - 0.007, name, size=5.8, color=col, weight="bold", ha="left")
    label(ax, 0.369, yi - 0.017, desc, size=5.2, color=T_MUTED, ha="left")

# Secrets
box(ax, 0.696, 0.205, 0.285, 0.192, "#0d1117", border_color=BORDER)
label(ax, 0.838, 0.400, "SECRETS & ENV", size=6, color=T_ROSE, weight="bold")
secrets_list = [
    ("ANTHROPIC_API_KEY",      "sk-ant-...  ·  GitHub + SSM Parameter Store",    T_GREEN),
    ("GOOGLE_API_KEY",         "AIza...  ·  GitHub + SSM Parameter Store",        T_AMBER),
    ("AWS_ACCESS_KEY_ID",      "AKIA...  ·  GitHub secret (ECR push)",            T_AMBER),
    ("AWS_SECRET_ACCESS_KEY",  "IAM secret  ·  GitHub secret",                   T_MUTED),
    ("EC2_SSH_PRIVATE_KEY",    ".pem contents  ·  GitHub secret",                T_MUTED),
    ("AZURE_CREDENTIALS",      "SPN JSON  ·  GitHub secret (Azure deploy)",      T_MUTED),
    ("JIRA_API_TOKEN",         "Atlassian PAT  ·  GitHub + container",            T_MUTED),
]
for i, (name, desc, col) in enumerate(secrets_list):
    yi = 0.385 - i * 0.025
    label(ax, 0.703, yi,        name, size=5.8, color=col, weight="bold", ha="left")
    label(ax, 0.703, yi - 0.011, desc, size=5.2, color=T_MUTED, ha="left")

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 5 — Output + Docker + Model Presets
# ═══════════════════════════════════════════════════════════════════════════════
box(ax, 0.01, 0.040, 0.98, 0.140, PANEL_BG, border_color="#444c56")
section_header(ax, 0.01, 0.186, 0.98, "OUTPUT  ·  DOCKER  ·  MODEL PRESETS", color=T_MUTED)

# Output
box(ax, 0.018, 0.050, 0.275, 0.128, "#0d1117", border_color=BORDER)
label(ax, 0.155, 0.180, "PIPELINE OUTPUT", size=6, color=T_ACCENT, weight="bold")
for i, o in enumerate([
    "epics[] + stories[] + tasks[]  (nested hierarchy)",
    "gaps[]  ·  conflicts[]  ·  duplicates[]",
    "synthesis.json  ·  synthesis.md",
    "audit_trail.md  ·  chain fingerprint",
    "Jira push: Epic → Story → Sub-task",
    "Prometheus metrics  ·  OTLP spans",
]):
    label(ax, 0.025, 0.165 - i * 0.019, o, size=5.8, color=T_MUTED, ha="left")

# Docker
box(ax, 0.306, 0.050, 0.285, 0.128, "#0d1117", border_color=BORDER)
label(ax, 0.448, 0.180, "DOCKER  ·  Multi-Stage Build", size=6, color=T_AMBER, weight="bold")
for i, d in enumerate([
    "Stage 1 builder: python:3.13-slim + build-essential → wheels",
    "Stage 2 runtime: packages only  ·  −200MB  ·  UID 1000 non-root",
    "warmup.py: bakes all-MiniLM-L6-v2 into image layer (no cold-start)",
    "libgomp1: OpenMP for numpy/sentence-transformers on slim",
    "HEALTHCHECK: /_stcore/health  30s interval  60s start-period",
    "STOPSIGNAL SIGTERM  ·  ENTRYPOINT /app/entrypoint.sh",
]):
    label(ax, 0.313, 0.165 - i * 0.019, d, size=5.8, color=T_MUTED, ha="left")

# Model Presets
box(ax, 0.604, 0.050, 0.385, 0.128, "#0d1117", border_color=BORDER)
label(ax, 0.796, 0.180, "MODEL PRESETS  ·  per-stage override via advanced sidebar", size=6, color=T_GREEN, weight="bold")
col_x = [0.612, 0.660, 0.728, 0.806, 0.895]
col_h = ["Preset", "Parse", "Constraint", "Stories + Gap", "Epic"]
col_colors = [T_PRIMARY, T_ACCENT, T_ACCENT, T_AMBER, T_ACCENT]
for j, (h, cx, cc) in enumerate(zip(col_h, col_x, col_colors)):
    label(ax, cx, 0.163, h, size=5.8, color=cc, weight="bold", ha="left")
presets = [
    ("Open",     "gemini-flash",    "gemini-flash",    "gemini-flash",    "gemini-flash",    T_GREEN),
    ("Hybrid", "gemini-flash",    "gemini-flash",    "claude-haiku",    "gemini-flash",    T_AMBER),
    ("Elite",  "claude-haiku",    "claude-haiku",    "claude-haiku",    "claude-haiku",    T_ROSE),
]
for i, (preset, p, c, s, e, pc) in enumerate(presets):
    yi = 0.150 - i * 0.022
    for j, (cell, cx) in enumerate(zip([preset, p, c, s, e], col_x)):
        label(ax, cx, yi, cell, size=5.5,
              color=pc if j == 0 else T_MUTED, ha="left",
              weight="bold" if j == 0 else "normal")

# ── Legend ────────────────────────────────────────────────────────────────────
legend = [
    (C_AGENT, T_ACCENT, "LangGraph Agent"),
    (C_TOOL,  T_AMBER,  "Deterministic Tool"),
    (C_SECURITY, T_ROSE, "Security / Guard"),
    (C_INFRA, T_GREEN,  "Azure Infra"),
    (C_AUTH,  T_VIOLET, "Auth / OAuth2"),
    (C_LLM,   T_GREEN,  "LLM Provider"),
    (C_MEMORY,T_AMBER,  "Memory / Audit"),
]
lx = 0.015
for col, tc, lbl in legend:
    box(ax, lx, 0.010, 0.011, 0.018, col)
    label(ax, lx + 0.016, 0.019, lbl, size=5.5, color=tc, ha="left")
    lx += 0.128

ax.text(0.5, 0.002,
        "Claude + Gemini providers  ·  deterministic dedup & guardrails  ·  tamper-evident audit log  ·  HMAC-signed OAuth state  ·  Azure Container Apps (canary)",
        fontsize=5.2, color=T_MUTED, ha="center", va="bottom", style="italic")

plt.tight_layout(pad=0.2)
plt.savefig("architecture_diagram.png", dpi=180, bbox_inches="tight",
            facecolor=BG, edgecolor="none")
print("✅ architecture_diagram.png written")
