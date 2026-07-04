# Backlog Synthesizer — Operations Runbook

> **Audience:** On-call engineers and SREs.  
> **Last reviewed:** 2026-07-03

---

## 1. Service overview

| Item | Value |
|---|---|
| Runtime | Python 3.13, Streamlit, LangGraph |
| Container | `backlog-synthesizer:latest` (multi-stage, non-root `appuser`) |
| Health endpoint | `GET /_stcore/health` → HTTP 200 |
| Metrics endpoint | `GET :9090/metrics` (Prometheus scrape) |
| Persistent data | `LOGS_DIR` + `OUTPUTS_DIR` (Azure Files share / EFS volume mount) |
| Auth | None (no login wall — local user assumed) |
| LLM providers | Anthropic Claude · Google Gemini (Open / Hybrid presets) |

---

## 2. Alert runbook

### 2.1 `SecurityFinding` alert — injection / PII / toxicity

**Trigger:** `post_security_alert` fired one or more `error`-severity findings.  
**Source:** Slack/Teams webhook or PagerDuty (configured via `SECURITY_WEBHOOK_URL` / `PAGERDUTY_ROUTING_KEY`).

**Response:**
1. Open the audit log (`AUDIT_DB_PATH`, default `logs/audit_chain.db`) and filter by `run_id` from the alert payload.
2. Look for `injection_scan_findings` or `output_security_finding` records — they contain the full finding details.
3. If the finding is `injection_*`: the offending text was already redacted before reaching any LLM. No further action unless this is a coordinated attack pattern — consider blocking the user.
4. If the finding is `pii_*` or `toxicity_*`: check whether the story was published to Jira. If so, delete or redact it there immediately. Notify the data owner.
5. If `bias_*` (severity `warn`): raise in the next sprint review; no immediate action required.
6. Escalate to the security team if `injection_*` findings recur from the same user within 1 hour.

---

### 2.2 Circuit breaker OPEN — `anthropic` or `google`

**Symptom:** `Circuit breaker OPEN for anthropic after N consecutive failure(s)` in logs.  
**Impact:** All new synthesis runs using that provider fast-fail until the breaker recovers (default 60 s probe window).

**Response:**
1. Check `LLM_ERRORS_TOTAL` in Prometheus for the failing provider.
2. Verify API key validity: `curl -H "x-api-key: $ANTHROPIC_API_KEY" https://api.anthropic.com/v1/models`.
3. Check the provider's status page (status.anthropic.com / status.cloud.google.com).
4. If the key is rotated in the platform secrets manager, restart the container to pick up the new value: `kubectl rollout restart deployment/backlog-synthesizer` or `az containerapp update --name … --revision-weight latest=100`.
5. The breaker self-heals after `CB_RECOVERY_TIMEOUT_SEC` (default 60 s). No manual reset needed unless the API key is genuinely invalid.

---

### 2.3 Budget exceeded — user blocked

**Symptom:** User sees "Daily budget exceeded" in the UI.  
**Impact:** Single user blocked; other users unaffected.

**Response:**
1. Verify Redis spend counter: `redis-cli HGETALL budget:<user_id>:<YYYYMMDD>`.
2. If the block is a false positive (Redis data corruption): `redis-cli DEL budget:<user_id>:<YYYYMMDD>` to reset the counter.
3. To raise the per-user daily limit, update `DAILY_BUDGET_USD` in `ui/run_history.py` and redeploy, or set the env var if it has been extracted.
4. If `REDIS_REQUIRED=1` and Redis is down: the app will have refused to start. Restore Redis before restarting.

---

### 2.4 Container OOM / slow synthesis

**Symptom:** Container restarted (`OOMKilled`), or synthesis takes > 10 min.

**Response:**
1. Check `ACTIVE_SYNTHESIS` gauge in Prometheus — if it equals `MAX_CONCURRENT_SYNTHESES`, the semaphore is saturated; users are queuing.
2. Scale out: increase replica count or raise `MAX_CONCURRENT_SYNTHESES` (CPU/RAM permitting).
3. Check `SYNTHESIS_DURATION_SECONDS` histogram — p99 > 300 s indicates LLM timeout or infinite retry loop. Verify `LLM_CALL_TIMEOUT_SECONDS` (default 120 s) is propagated.
4. If OOMKilled: the sentence-transformer model loads ~500 MB. Ensure container memory limit ≥ 2 GB. The warm-up runs at image build time (`src/warmup.py`); a cold-start with no warm-up layer doubles the load time.

---

### 2.5 Startup failure — missing env var

**Symptom:** Container exits immediately with `Configuration error: Missing required environment variable(s)`.

**Response:**
1. Check container logs for the missing variable name.
2. Set the missing secret in the platform secrets manager (Azure Key Vault / Container Apps secrets).
3. Redeploy or restart — the startup check runs at boot and will pass once the var is present.
4. **Never** commit secrets to `.env` in the repo. Use `.env.example` as the template for local dev.

---

### 2.6 Audit log full / SQLite locked

**Symptom:** `database is locked` or `disk full` errors in logs.

**Response:**
1. Check disk usage on the persistent volume (`df -h /app`).
2. Manually trigger retention purge (if `AUDIT_LOG_RETENTION_DAYS` is set):
   ```python
   from memory.audit_log import AuditLog
   AuditLog.purge_old_runs()
   ```
3. If `AUDIT_LOG_RETENTION_DAYS=0` (keep forever): set a non-zero value and redeploy, or manually run the purge above.
4. If disk is full on the volume: expand it in the cloud portal and restart the app.

---

## 3. GitHub Actions workflows

### 3.1 Application workflows

| Workflow | File | Trigger | What it does |
|---|---|---|---|
| Tests & Quality | `ci.yml` | Push / PR to `main`, manual | Lint, unit tests, Docker build verification, optional eval suite |
| Deploy — AWS | `cd-aws.yml` | Push to `main` | Build image → push to ECR → SSH deploy to EC2 → smoke test |
| Deploy — Azure | `cd-azure.yml` | Manual (`workflow_dispatch`) | Canary deploy to Azure Container Apps |

### 3.2 Infrastructure workflows (Terraform)

| Workflow | File | Trigger | What it does |
|---|---|---|---|
| Infra — AWS | `infra-aws.yml` | PR touching `infra/aws/**` | `terraform plan` — posts output as PR comment |
| | | Push to `main` touching `infra/aws/**` | `terraform apply` — gated on `aws-production` environment approval |
| | | Manual dispatch | Choose `plan`, `apply`, or `destroy` |
| Infra — Azure | `infra-azure.yml` | PR touching `infra/azure/**` | `terraform plan` — posts output as PR comment |
| | | Push to `main` touching `infra/azure/**` | `terraform apply` — gated on `azure-production` environment approval |
| | | Manual dispatch | Choose `plan`, `apply`, or `destroy` |

**Terraform state backends:**
- AWS: S3 bucket + DynamoDB lock table (names in `TF_STATE_BUCKET` / `TF_STATE_LOCK_TABLE` secrets)
- Azure: Azure Blob Storage account (names in `TF_STATE_STORAGE_ACCOUNT` / `TF_STATE_RESOURCE_GROUP` secrets)

### 3.3 Triggering a manual infrastructure change

```bash
# Via GitHub CLI — run plan only (safe, no changes)
gh workflow run infra-aws.yml --field action=plan
gh workflow run infra-azure.yml --field action=plan

# Apply — requires approval in the aws-production / azure-production environment
gh workflow run infra-aws.yml --field action=apply
gh workflow run infra-azure.yml --field action=apply

# Destroy — use with extreme caution
gh workflow run infra-aws.yml --field action=destroy
gh workflow run infra-azure.yml --field action=destroy
```

### 3.4 Workflow failure runbook

| Symptom | Likely cause | Fix |
|---|---|---|
| `infra-aws.yml` fails on `terraform init` | `TF_STATE_BUCKET` secret missing or S3 bucket doesn't exist | Bootstrap the bucket (see workflow file comments), then re-run |
| `infra-azure.yml` fails on `terraform init` | `TF_STATE_STORAGE_ACCOUNT` doesn't exist or credentials wrong | Bootstrap the storage account, verify `ARM_*` secrets |
| Plan posts to PR then apply never runs | `aws-production` / `azure-production` environment not created | Create under Settings → Environments and add required reviewers |
| `cd-aws.yml` fails at SSH deploy | EC2 instance not running or IP changed | Check EC2 console; update `EC2_HOST` secret if IP changed |
| `cd-azure.yml` fails at image push | `AZURE_CREDENTIALS` expired | Rotate the service principal (§4.3) |
| `ci.yml` eval job skipped | `ANTHROPIC_API_KEY` secret not set | Add the secret; forks skip the eval silently by design |

---

## 5. Rollback procedure

### Rolling back a bad deploy

**Azure Container Apps:**
```bash
# List revisions
az containerapp revision list --name backlog-synthesizer --resource-group <rg> -o table

# Activate a previous revision
az containerapp revision activate \
  --name backlog-synthesizer --resource-group <rg> \
  --revision <previous-revision-name>

# Shift 100% of traffic to it
az containerapp ingress traffic set \
  --name backlog-synthesizer --resource-group <rg> \
  --revision-weight <previous-revision-name>=100
```

---

## 6. Key rotation

### 6.1 Automated rotation check

A GitHub Actions workflow (`.github/workflows/secret-rotation-check.yml`) runs **every Monday at 08:00 UTC** and:

- Makes a lightweight API call to each configured provider to verify the key is still accepted
- Checks Azure Key Vault for secrets expiring within 14 days (if `AZURE_KEY_VAULT_NAME` is set)
- Posts a Slack/Teams alert to `SECURITY_WEBHOOK_URL` on failure
- Opens a GitHub issue automatically if `ANTHROPIC_API_KEY` is invalid

Trigger manually after any suspected credential leak:  
`Actions → Secret rotation check → Run workflow`

---

### 6.2 Rotation schedule

| Secret | Recommended max age | Last rotation field |
|---|---|---|
| `ANTHROPIC_API_KEY` | 90 days | Track in your secrets manager |
| `GOOGLE_API_KEY` | 90 days | Track in your secrets manager |
| `JIRA_API_TOKEN` | 90 days | Track in your secrets manager |
| `ARM_CLIENT_SECRET` (Azure SP) | 180 days | Set expiry in Azure App Registration |
| `AWS_SECRET_ACCESS_KEY` | 90 days | Rotate in AWS IAM |
| `PAGERDUTY_ROUTING_KEY` | 365 days | Track in PagerDuty console |

> Tip: set an expiry date on each secret in Azure Key Vault. The weekly CI job will warn 14 days before expiry.

---

### 6.3 Rotation procedure

| Secret | Rotation steps |
|---|---|
| `ANTHROPIC_API_KEY` | Generate new key at console.anthropic.com → update GitHub Secret + platform secret → restart container → re-run rotation check workflow to confirm |
| `GOOGLE_API_KEY` | Rotate at console.cloud.google.com → update GitHub Secret + platform secret → restart → confirm |
| `JIRA_API_TOKEN` | Revoke at id.atlassian.com → generate new → update GitHub Secret + platform secret → restart → confirm |
| `ARM_CLIENT_SECRET` | Add a new credential in Azure App Registration → update `ARM_CLIENT_SECRET` GitHub Secret → delete old credential |
| `AWS_SECRET_ACCESS_KEY` | Create new IAM access key → update `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` GitHub Secrets → deactivate old key in IAM → delete old key |

**Zero-downtime rotation for `ANTHROPIC_API_KEY`:**  
Set the new key in your secrets manager first. Then do a rolling restart (Container Apps revision) — old pods use the old key until they are replaced; new pods pick up the new key from the environment at startup. There is no window where both keys need to be valid simultaneously.

---

## 7. Useful queries

### Prometheus

```promql
# Current active syntheses
backlog_active_syntheses

# Error rate (last 5 min)
rate(backlog_llm_errors_total[5m])

# p95 synthesis latency
histogram_quantile(0.95, rate(backlog_synthesis_duration_seconds_bucket[10m]))

# Total cost today
increase(backlog_synthesis_cost_usd_total[24h])
```

### Audit log (SQLite)

```sql
-- Last 10 security findings
SELECT run_id, agent, action, payload, ts
FROM audit_log
WHERE action IN ('injection_scan_findings', 'output_security_finding')
ORDER BY ts DESC LIMIT 10;

-- Syntheses per user today
SELECT user_email, COUNT(*) AS runs
FROM audit_log
WHERE action = 'pipeline_completed'
  AND ts >= date('now', 'start of day')
GROUP BY user_email ORDER BY runs DESC;
```

---

## 8. On-call contacts

| Role | Contact |
|---|---|
| Primary on-call | Rotate per team schedule in PagerDuty |
| Security incidents | security@yourcompany.com (P1 only) |
| Data/GDPR concerns | dpo@yourcompany.com |
| LLM provider issues | Anthropic support · Google Cloud support |

---

## 9. Disaster recovery

| Scenario | RTO | RPO | Procedure |
|---|---|---|---|
| Single container crash | < 2 min | 0 (stateless) | Health check triggers automatic restart |
| Bad deploy | < 5 min | 0 | Rollback via previous container revision (§3) |
| Redis failure (budget store) | < 1 min | budget counters reset | Remove `REDIS_REQUIRED`, restart — falls back to file-based |
| Persistent volume corruption | < 30 min | last backup | Restore from volume snapshot; audit log and outputs are the only persistent state |
| Full region outage | < 60 min | last cross-region backup | Re-deploy to secondary region using the same image digest |
