# ═══════════════════════════════════════════════════════════════════════════════
# Azure Key Vault — staging application secrets
# ═══════════════════════════════════════════════════════════════════════════════
#
# Secret VALUES are injected from sensitive Terraform variables (TF_VAR_* supplied
# by CI from GitHub Actions secrets). They are NEVER committed to git — only the
# vault, access policies, and the secret *names* are defined here.
#
# The staging Container App reads these at runtime via its system-assigned managed
# identity (see the `secret { key_vault_secret_id ... identity = "System" }` blocks
# in main.tf), so no plaintext secret is stored on the container app itself.
#
# Cold-apply note: the staging app's identity only exists after the app is created,
# and `azurerm_key_vault_access_policy.staging_app` grants it read access after that.
# On a brand-new environment, run `terraform apply` once to create the app + policy;
# if the first revision cannot resolve a Key Vault reference because the policy was
# applied moments later, restart the revision (or re-run apply) to pick it up.

resource "azurerm_key_vault" "main" {
  name                       = var.key_vault_name
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = false
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  tags                       = local.tags
}

# Deployer service principal may manage secret values.
resource "azurerm_key_vault_access_policy" "deployer" {
  key_vault_id       = azurerm_key_vault.main.id
  tenant_id          = var.tenant_id
  object_id          = var.spn_object_id
  secret_permissions = ["Get", "List", "Set", "Delete", "Purge", "Recover"]
}

# Staging app's system-assigned managed identity may READ secret values.
resource "azurerm_key_vault_access_policy" "staging_app" {
  key_vault_id       = azurerm_key_vault.main.id
  tenant_id          = var.tenant_id
  object_id          = azurerm_container_app.staging.identity[0].principal_id
  secret_permissions = ["Get", "List"]
}

# The four application secrets. Values come from sensitive variables (CI-injected).
locals {
  kv_secrets = {
    "anthropic-api-key" = var.anthropic_api_key
    "google-api-key"    = var.google_api_key
    "jira-api-token"    = var.jira_api_token
  }
}

resource "azurerm_key_vault_secret" "app" {
  for_each     = local.kv_secrets
  name         = each.key
  value        = each.value
  key_vault_id = azurerm_key_vault.main.id

  # Must wait for the deployer access policy before secret values can be written.
  depends_on = [azurerm_key_vault_access_policy.deployer]
}
