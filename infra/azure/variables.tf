# ── Azure credentials ─────────────────────────────────────────────────────────
variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "tenant_id" {
  description = "Azure Tenant ID"
  type        = string
}

variable "client_id" {
  description = "Service Principal Application (client) ID"
  type        = string
}

variable "client_secret" {
  description = "Service Principal client secret"
  type        = string
  sensitive   = true
}

# ── Infrastructure ────────────────────────────────────────────────────────────
variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
  default     = "rg-backlog-synthesizer"
}

variable "acr_name" {
  description = "Azure Container Registry name (globally unique, alphanumeric)"
  type        = string
}

variable "acr_sku" {
  description = "ACR SKU: Basic | Standard | Premium"
  type        = string
  default     = "Basic"
}

variable "container_app_env_name" {
  description = "Container Apps environment name"
  type        = string
  default     = "cae-backlog-synthesizer"
}

variable "app_name_staging" {
  description = "Staging Container App name"
  type        = string
  default     = "backlog-synthesizer-staging"
}

variable "app_name_prod" {
  description = "Production Container App name"
  type        = string
  default     = "backlog-synthesizer-prod"
}

variable "spn_object_id" {
  description = "Object ID of the GitHub Actions SPN (for ACR role assignment)"
  type        = string
}

# ── App configuration ─────────────────────────────────────────────────────────
variable "anthropic_api_key" {
  description = "Anthropic API key"
  type        = string
  sensitive   = true
}

variable "google_api_key" {
  description = "Google Gemini API key (optional)"
  type        = string
  sensitive   = true
  default     = ""
}

# ── Jira ──────────────────────────────────────────────────────────────────────
variable "jira_base_url" {
  description = "Jira base URL"
  type        = string
  default     = ""
}

variable "jira_email" {
  description = "Jira account email"
  type        = string
  default     = ""
}

variable "jira_api_token" {
  description = "Jira API token"
  type        = string
  sensitive   = true
  default     = ""
}

variable "jira_project_key" {
  description = "Jira project key"
  type        = string
  default     = "QT"
}

# ── Scaling ───────────────────────────────────────────────────────────────────
variable "staging_min_replicas" {
  description = "Minimum replicas for staging (0 = scale to zero)"
  type        = number
  default     = 0
}

variable "staging_max_replicas" {
  description = "Maximum replicas for staging"
  type        = number
  default     = 1
}

variable "prod_min_replicas" {
  description = "Minimum replicas for production"
  type        = number
  default     = 1
}

variable "prod_max_replicas" {
  description = "Maximum replicas for production"
  type        = number
  default     = 3
}

variable "cpu_requests" {
  description = "CPU cores per replica"
  type        = string
  default     = "1.0"
}

variable "memory_requests" {
  description = "Memory per replica"
  type        = string
  default     = "2Gi"
}

variable "storage_account_name" {
  description = "Storage account backing the Azure Files shares for persistent logs/outputs (globally unique, 3-24 lowercase alphanumeric)"
  type        = string
}

variable "key_vault_name" {
  description = "Key Vault holding the staging app secrets (globally unique, 3-24 chars)"
  type        = string
}
