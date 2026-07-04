terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Partial backend — CI injects values via -backend-config flags.
  # Bootstrap: aws s3api create-bucket --bucket <TF_STATE_BUCKET> --region <region>
  #            aws dynamodb create-table --table-name <TF_STATE_LOCK_TABLE> \
  #              --attribute-definitions AttributeName=LockID,AttributeType=S \
  #              --key-schema AttributeName=LockID,KeyType=HASH \
  #              --billing-mode PAY_PER_REQUEST
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project    = "backlog-synthesizer"
      managed_by = "terraform"
    }
  }
}
