output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "acr_admin_username" {
  value     = azurerm_container_registry.main.admin_username
  sensitive = true
}

output "container_app_env_domain" {
  value = azurerm_container_app_environment.main.default_domain
}

output "staging_url" {
  value = "https://${azurerm_container_app.staging.ingress[0].fqdn}"
}

output "prod_url" {
  value = "https://${azurerm_container_app.prod.ingress[0].fqdn}"
}

output "key_vault_uri" {
  description = "Key Vault URI holding the staging app secrets"
  value       = azurerm_key_vault.main.vault_uri
}

output "storage_account_name" {
  description = "Storage account backing the persistent logs/outputs file shares"
  value       = azurerm_storage_account.main.name
}
