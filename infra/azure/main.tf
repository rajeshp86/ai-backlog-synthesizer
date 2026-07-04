# ═══════════════════════════════════════════════════════════════════════════════
# Backlog Synthesizer
# Azure infrastructure: ACR + Container Apps (staging + prod)
# ═══════════════════════════════════════════════════════════════════════════════

locals {
  tags = {
    project     = "backlog-synthesizer"
    managed_by  = "terraform"
    environment = "shared"
  }
}

# ── Resource Group ────────────────────────────────────────────────────────────
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

# ── Log Analytics (required by Container Apps environment) ────────────────────
resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-backlog-synthesizer"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

# ── Azure Container Registry ──────────────────────────────────────────────────
resource "azurerm_container_registry" "main" {
  name                = var.acr_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = var.acr_sku
  admin_enabled       = true
  tags                = local.tags
}

# Allow the GitHub Actions SPN to push images to ACR
resource "azurerm_role_assignment" "acr_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = var.spn_object_id
}

# Allow the staging app's managed identity to PULL images from ACR (so the
# container app authenticates to the registry via identity, not a password).
resource "azurerm_role_assignment" "staging_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app.staging.identity[0].principal_id
}

# ── Storage Account (persistent logs & outputs) ───────────────────────────────
resource "azurerm_storage_account" "main" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  tags                     = local.tags
}

resource "azurerm_storage_share" "logs" {
  name               = "backlog-logs"
  storage_account_id = azurerm_storage_account.main.id
  quota              = 10
}

resource "azurerm_storage_share" "outputs" {
  name               = "backlog-outputs"
  storage_account_id = azurerm_storage_account.main.id
  quota              = 50
}

# ── Container Apps Environment ────────────────────────────────────────────────
resource "azurerm_container_app_environment" "main" {
  name                       = var.container_app_env_name
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}

# Mount Azure Files into Container Apps environment
resource "azurerm_container_app_environment_storage" "logs" {
  name                         = "logs-share"
  container_app_environment_id = azurerm_container_app_environment.main.id
  account_name                 = azurerm_storage_account.main.name
  share_name                   = azurerm_storage_share.logs.name
  access_key                   = azurerm_storage_account.main.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_container_app_environment_storage" "outputs" {
  name                         = "outputs-share"
  container_app_environment_id = azurerm_container_app_environment.main.id
  account_name                 = azurerm_storage_account.main.name
  share_name                   = azurerm_storage_share.outputs.name
  access_key                   = azurerm_storage_account.main.primary_access_key
  access_mode                  = "ReadWrite"
}

# ── Common env vars (shared between staging and prod) ─────────────────────────
locals {
  app_env_vars = [
    { name = "ANTHROPIC_API_KEY",    secret_name = "anthropic-api-key" },
    { name = "GOOGLE_API_KEY",       secret_name = "google-api-key" },
    { name = "JIRA_BASE_URL",        value = var.jira_base_url },
    { name = "JIRA_EMAIL",           value = var.jira_email },
    { name = "JIRA_API_TOKEN",       secret_name = "jira-api-token" },
    { name = "JIRA_PROJECT_KEY",     value = var.jira_project_key },
    { name = "CONFLUENCE_BASE_URL",  value = var.jira_base_url },
    { name = "CONFLUENCE_EMAIL",     value = var.jira_email },
    { name = "CONFLUENCE_API_TOKEN", secret_name = "jira-api-token" },
    { name = "LOGS_DIR",             value = "/app/data/logs" },
    { name = "OUTPUTS_DIR",          value = "/app/data/outputs" },
    { name = "AUDIT_DB_PATH",        value = "/app/data/logs/audit_chain.db" },
  ]

  secrets = [
    { name = "anthropic-api-key", value = var.anthropic_api_key },
    { name = "google-api-key",    value = var.google_api_key },
    { name = "jira-api-token",    value = var.jira_api_token },
    { name = "acr-password",      value = azurerm_container_registry.main.admin_password },
  ]
}

# ── Staging Container App ─────────────────────────────────────────────────────
resource "azurerm_container_app" "staging" {
  name                         = var.app_name_staging
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = merge(local.tags, { environment = "staging" })

  # System-assigned managed identity — used to read secrets from Key Vault.
  identity {
    type = "SystemAssigned"
  }

  # App secrets are Key Vault REFERENCES — the value lives only in Key Vault and
  # is fetched at runtime via the system-assigned identity. No plaintext secret
  # is ever stored on the container app (ACR auth uses the identity too — below).
  dynamic "secret" {
    for_each = azurerm_key_vault_secret.app
    content {
      name                = secret.value.name
      key_vault_secret_id = secret.value.versionless_id
      identity            = "System"
    }
  }

  # ACR pull authenticated via the app's managed identity (AcrPull role granted
  # below) — no registry username/password is stored anywhere.
  registry {
    server   = azurerm_container_registry.main.login_server
    identity = "System"
  }

  ingress {
    external_enabled = true
    target_port      = 8502
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = var.staging_min_replicas
    max_replicas = var.staging_max_replicas

    volume {
      name         = "data"
      storage_type = "AzureFile"
      storage_name = "logs-share"
    }

    container {
      name   = "backlog-synthesizer"
      image  = "${azurerm_container_registry.main.login_server}/backlog-synthesizer:latest"
      cpu    = var.cpu_requests
      memory = var.memory_requests

      dynamic "env" {
        for_each = [for e in local.app_env_vars : e if lookup(e, "value", null) != null]
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      dynamic "env" {
        for_each = [for e in local.app_env_vars : e if lookup(e, "secret_name", null) != null]
        content {
          name        = env.value.name
          secret_name = env.value.secret_name
        }
      }

      volume_mounts {
        name = "data"
        path = "/app/data"
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/_stcore/health"
        port      = 8502
        initial_delay    = 60
        interval_seconds = 30
        timeout          = 5
        failure_count_threshold = 3
      }

      readiness_probe {
        transport = "HTTP"
        path      = "/_stcore/health"
        port      = 8502
        interval_seconds = 10
        timeout          = 5
        failure_count_threshold = 3
      }
    }
  }
}

# ── Production Container App ──────────────────────────────────────────────────
resource "azurerm_container_app" "prod" {
  name                         = var.app_name_prod
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Multiple"
  tags                         = merge(local.tags, { environment = "production" })

  dynamic "secret" {
    for_each = local.secrets
    content {
      name  = secret.value.name
      value = secret.value.value
    }
  }

  registry {
    server               = azurerm_container_registry.main.login_server
    username             = azurerm_container_registry.main.admin_username
    password_secret_name = "acr-password"
  }

  ingress {
    external_enabled = true
    target_port      = 8502
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = var.prod_min_replicas
    max_replicas = var.prod_max_replicas

    volume {
      name         = "data"
      storage_type = "AzureFile"
      storage_name = "outputs-share"
    }

    container {
      name   = "backlog-synthesizer"
      image  = "${azurerm_container_registry.main.login_server}/backlog-synthesizer:latest"
      cpu    = var.cpu_requests
      memory = var.memory_requests

      dynamic "env" {
        for_each = [for e in local.app_env_vars : e if lookup(e, "value", null) != null]
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      dynamic "env" {
        for_each = [for e in local.app_env_vars : e if lookup(e, "secret_name", null) != null]
        content {
          name        = env.value.name
          secret_name = env.value.secret_name
        }
      }

      volume_mounts {
        name = "data"
        path = "/app/data"
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/_stcore/health"
        port      = 8502
        initial_delay    = 60
        interval_seconds = 30
        timeout          = 5
        failure_count_threshold = 3
      }

      readiness_probe {
        transport = "HTTP"
        path      = "/_stcore/health"
        port      = 8502
        interval_seconds = 10
        timeout          = 5
        failure_count_threshold = 3
      }
    }
  }
}
