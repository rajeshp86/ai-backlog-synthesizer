output "app_url" {
  description = "Public URL for the Streamlit UI"
  value       = "http://${aws_eip.app.public_ip}:${var.app_port}"
}

output "elastic_ip" {
  description = "Static Elastic IP address of the EC2 instance"
  value       = aws_eip.app.public_ip
}

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.app.id
}

output "ecr_repository_url" {
  description = "ECR repository URL — use this as the Docker image registry"
  value       = aws_ecr_repository.app.repository_url
}

output "ecr_registry" {
  description = "ECR registry hostname (for docker login)"
  value       = split("/", aws_ecr_repository.app.repository_url)[0]
}

output "s3_bucket" {
  description = "S3 bucket name for synthesis outputs"
  value       = aws_s3_bucket.outputs.id
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = "ssh -i ~/.ssh/${var.key_pair_name}.pem ec2-user@${aws_eip.app.public_ip}"
}

output "deploy_command" {
  description = "Re-deploy the latest ECR image without re-running Terraform"
  value       = "ssh -i ~/.ssh/${var.key_pair_name}.pem ec2-user@${aws_eip.app.public_ip} 'sudo systemctl restart backlog-synthesizer'"
}

# ── GitHub Actions secrets ─────────────────────────────────────────────────
output "github_secret_AWS_ACCESS_KEY_ID" {
  description = "GitHub secret: AWS_ACCESS_KEY_ID"
  value       = aws_iam_access_key.github_actions.id
}

output "github_secret_AWS_SECRET_ACCESS_KEY" {
  description = "GitHub secret: AWS_SECRET_ACCESS_KEY"
  value       = aws_iam_access_key.github_actions.secret
  sensitive   = true
}

output "github_secret_AWS_REGION" {
  description = "GitHub secret: AWS_REGION"
  value       = var.aws_region
}

output "github_secret_ECR_REGISTRY" {
  description = "GitHub secret: ECR_REGISTRY"
  value       = split("/", aws_ecr_repository.app.repository_url)[0]
}

output "github_secret_EC2_HOST" {
  description = "GitHub secret: EC2_HOST"
  value       = aws_eip.app.public_ip
}

output "all_github_secrets" {
  description = "All values needed as GitHub Actions secrets (run: terraform output -json all_github_secrets)"
  sensitive   = true
  value = {
    AWS_ACCESS_KEY_ID     = aws_iam_access_key.github_actions.id
    AWS_SECRET_ACCESS_KEY = aws_iam_access_key.github_actions.secret
    AWS_REGION            = var.aws_region
    ECR_REGISTRY          = split("/", aws_ecr_repository.app.repository_url)[0]
    EC2_HOST              = aws_eip.app.public_ip
  }
}
