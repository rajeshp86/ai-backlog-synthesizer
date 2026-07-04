#!/usr/bin/env bash
# =============================================================================
# Backlog Synthesizer — Azure Monitor alert rules
#
# Run ONCE after azure_setup.sh to create alert rules in Azure Monitor.
# Alerts fire into an Action Group (email + webhook) that you configure below.
#
# Prerequisites:
#   az login && az account set --subscription <id>
#   The Container App and Log Analytics workspace must already exist.
#
# Usage:
#   chmod +x config/alerts/azure_monitor_alerts.sh
#   ./config/alerts/azure_monitor_alerts.sh
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
RESOURCE_GROUP="rg-backlog-synthesizer"
CONTAINERAPP_NAME="backlog-synthesizer"
ALERT_EMAIL="oncall@your-company.com"              # ← update
SLACK_WEBHOOK=""                                   # ← optional Slack webhook URL
LOCATION="eastus"

# Colours
GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }

SUBSCRIPTION=$(az account show --query id -o tsv)

# ── 1. Action Group (where alerts are sent) ───────────────────────────────────
info "Creating Action Group: ag-backlog-synthesizer"
RECEIVERS="emailReceivers=[{name:'oncall',emailAddress:'${ALERT_EMAIL}',useCommonAlertSchema:true}]"
if [ -n "$SLACK_WEBHOOK" ]; then
  RECEIVERS="${RECEIVERS} webhookReceivers=[{name:'slack',serviceUri:'${SLACK_WEBHOOK}',useCommonAlertSchema:true}]"
fi

az monitor action-group create \
  --resource-group "$RESOURCE_GROUP" \
  --name "ag-backlog-synthesizer" \
  --short-name "backlog" \
  --action email oncall "$ALERT_EMAIL" \
  --output none 2>/dev/null || true
ok "Action group ready"

AG_ID=$(az monitor action-group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "ag-backlog-synthesizer" \
  --query id -o tsv)

# ── 2. Log Analytics workspace (for KQL-based alerts) ────────────────────────
# Container Apps stream logs to the Log Analytics workspace attached to the
# Container Apps Environment.  We look it up from the environment.
CAE_NAME=$(az containerapp show \
  --name "$CONTAINERAPP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.managedEnvironmentId" -o tsv | xargs basename)

LAW_ID=$(az containerapp env show \
  --name "$CAE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.appLogsConfiguration.logAnalyticsConfiguration.customerId" \
  -o tsv 2>/dev/null || echo "")

# ── 3. Application error rate alert ──────────────────────────────────────────
# Fires when more than 5 % of log lines in the last 10 minutes are ERROR level.
info "Creating alert: ApplicationErrorRateHigh"
az monitor scheduled-query create \
  --resource-group "$RESOURCE_GROUP" \
  --name "backlog-error-rate-high" \
  --scopes "/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${CONTAINERAPP_NAME}" \
  --condition-query \
    "ContainerAppConsoleLogs_CL
     | where Log_s contains '\"level\":\"ERROR\"' or Log_s contains '[ERROR]'
     | summarize ErrorCount=count() by bin(TimeGenerated, 10m)" \
  --condition "count ErrorCount > 5" \
  --window-size "PT10M" \
  --evaluation-frequency "PT5M" \
  --severity 2 \
  --description "More than 5 error log lines in 10 minutes (possible synthesis failure spike)" \
  --action-groups "$AG_ID" \
  --auto-mitigate true \
  --output none 2>/dev/null || \
  info "  (alert may already exist — skipping)"
ok "Error rate alert ready"

# ── 4. Container restart / crash alert ───────────────────────────────────────
info "Creating alert: ContainerRestartCountHigh"
az monitor metrics alert create \
  --resource-group "$RESOURCE_GROUP" \
  --name "backlog-restart-count-high" \
  --scopes "/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${CONTAINERAPP_NAME}" \
  --condition "avg RestartCount > 2" \
  --window-size "PT5M" \
  --evaluation-frequency "PT1M" \
  --severity 1 \
  --description "Container App restarted > 2 times in 5 min — possible crash loop" \
  --action "$AG_ID" \
  --output none 2>/dev/null || true
ok "Restart alert ready"

# ── 5. Memory pressure alert ─────────────────────────────────────────────────
info "Creating alert: MemoryUsageHigh"
az monitor metrics alert create \
  --resource-group "$RESOURCE_GROUP" \
  --name "backlog-memory-high" \
  --scopes "/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${CONTAINERAPP_NAME}" \
  --condition "avg WorkingSetBytes > 1800000000" \
  --window-size "PT5M" \
  --evaluation-frequency "PT2M" \
  --severity 2 \
  --description "Memory usage > 1.8 GB (container limit 2 GB) — risk of OOM kill" \
  --action "$AG_ID" \
  --output none 2>/dev/null || true
ok "Memory alert ready"

# ── 6. CPU saturation alert ───────────────────────────────────────────────────
info "Creating alert: CPUSaturation"
az monitor metrics alert create \
  --resource-group "$RESOURCE_GROUP" \
  --name "backlog-cpu-high" \
  --scopes "/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${CONTAINERAPP_NAME}" \
  --condition "avg CpuNanoCores > 900000000" \
  --window-size "PT10M" \
  --evaluation-frequency "PT2M" \
  --severity 3 \
  --description "CPU > 90 % of the 1-vCPU limit for 10 min" \
  --action "$AG_ID" \
  --output none 2>/dev/null || true
ok "CPU alert ready"

# ── 7. Eval-suite regression alert (Logic App / scheduled query) ──────────────
# The eval suite (ci.yml eval-suite job) exits non-zero when a regression
# > 10 % is detected — CI itself is the alert for eval regressions.
# If you also want Azure Monitor to fire on CI failure, configure the GitHub
# Actions → Azure DevOps integration and create a work item alert there.
info "NOTE: Eval regression alerting is handled by CI (ci.yml --fail-on-regression flag)."
info "      No separate Azure Monitor rule is needed for that case."

echo ""
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Azure Monitor alerts created successfully.   ${NC}"
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo ""
echo "Alerts notify: $ALERT_EMAIL"
echo "View in portal: https://portal.azure.com/#blade/Microsoft_Azure_Monitoring/AlertsManagementSummaryBlade"
