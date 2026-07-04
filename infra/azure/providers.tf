terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.110"
    }
  }

  # Partial backend — CI injects values via -backend-config flags.
  # Bootstrap: az group create -n <TF_STATE_RESOURCE_GROUP> -l eastus
  #            az storage account create -n <TF_STATE_STORAGE_ACCOUNT> -g <RG>
  #            az storage container create -n tfstate --account-name <SA>
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
  client_id       = var.client_id
  client_secret   = var.client_secret
}

