# ═══════════════════════════════════════════════════════════════════════════════
# Quantum Technologies — Backlog Synthesizer
# AWS Free Tier infrastructure: ECR + EC2 t2.micro + S3 + Elastic IP
#
# Free tier limits this targets:
#   EC2:  t2.micro  750 hrs/month (12 months)
#   ECR:  500 MB storage
#   S3:   5 GB storage, 20k GET, 2k PUT
#   EBS:  30 GB gp2/gp3
#   EIP:  free while attached to a running instance
#   SSM Parameter Store standard: 10,000 params free
#
# NOT included (costs money): ALB, RDS, ElastiCache, NAT Gateway.
# Access the UI directly via the Elastic IP on port 8502.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Use default VPC to avoid extra NAT gateway costs ─────────────────────────
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ── ECR — container image registry ───────────────────────────────────────────
resource "aws_ecr_repository" "app" {
  name                 = "backlog-synthesizer"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "backlog-synthesizer"
    environment = var.environment
  }
}

# Keep only the last 3 images to stay within the 500 MB free tier limit
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 3 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = { type = "expire" }
    }]
  })
}

# ── S3 — persistent outputs + embedding cache ─────────────────────────────────
resource "aws_s3_bucket" "outputs" {
  bucket = var.outputs_bucket_name

  tags = {
    Name        = "backlog-synthesizer-outputs"
    environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "outputs" {
  bucket = aws_s3_bucket.outputs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "outputs" {
  bucket = aws_s3_bucket.outputs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "outputs" {
  bucket                  = aws_s3_bucket.outputs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── IAM role for EC2 ─────────────────────────────────────────────────────────
resource "aws_iam_role" "ec2" {
  name = "backlog-synthesizer-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = {
    Name = "backlog-synthesizer-ec2-role"
  }
}

# ECR: pull images
resource "aws_iam_role_policy_attachment" "ecr_readonly" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# SSM: session manager (no bastion needed) + managed patches
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# S3: read/write the outputs bucket
resource "aws_iam_role_policy" "s3_outputs" {
  name = "backlog-synthesizer-s3-outputs"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.outputs.arn,
        "${aws_s3_bucket.outputs.arn}/*"
      ]
    }]
  })
}

# SSM Parameter Store: read app secrets under /backlog-synthesizer/*
resource "aws_iam_role_policy" "ssm_params" {
  name = "backlog-synthesizer-ssm-params"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ]
      Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/backlog-synthesizer/*"
    }]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "backlog-synthesizer-ec2-profile"
  role = aws_iam_role.ec2.name
}

# ── Security Group ────────────────────────────────────────────────────────────
resource "aws_security_group" "app" {
  name        = "backlog-synthesizer-sg"
  description = "Backlog Synthesizer — Streamlit UI + SSH"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Streamlit UI"
    from_port   = var.app_port
    to_port     = var.app_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH — restrict to your IP in production"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_allowed_cidr]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "backlog-synthesizer-sg"
    environment = var.environment
  }
}

# ── AMI: Amazon Linux 2023 (latest) ──────────────────────────────────────────
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── EC2 instance ──────────────────────────────────────────────────────────────
resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  key_name               = var.key_pair_name
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  vpc_security_group_ids = [aws_security_group.app.id]
  subnet_id              = tolist(sort(data.aws_subnets.default.ids))[0]

  user_data = base64encode(templatefile("${path.module}/userdata.sh", {
    aws_region   = var.aws_region
    ecr_repo_url = aws_ecr_repository.app.repository_url
    ssm_prefix   = "/backlog-synthesizer"
    app_port     = var.app_port
    s3_bucket    = aws_s3_bucket.outputs.id
  }))

  root_block_device {
    volume_size           = var.root_volume_size_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  # Replace the instance (blue/green) when user_data changes rather than in-place update
  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name        = "backlog-synthesizer"
    environment = var.environment
  }
}

# ── Elastic IP — static address survives instance restarts ───────────────────
# Allocate the EIP separately from the association so that create_before_destroy
# on the instance does not race with AWS's single-association limit.
resource "aws_eip" "app" {
  domain = "vpc"

  tags = {
    Name        = "backlog-synthesizer-eip"
    environment = var.environment
  }
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}

# ── IAM user for GitHub Actions (ECR push) ───────────────────────────────────
resource "aws_iam_user" "github_actions" {
  name = "backlog-synthesizer-github-actions"

  tags = {
    Name = "backlog-synthesizer-github-actions"
  }
}

resource "aws_iam_user_policy" "github_actions_ecr" {
  name = "backlog-synthesizer-ecr-push"
  user = aws_iam_user.github_actions.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRAuth"
        Effect = "Allow"
        Action = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeRepositories",
          "ecr:ListImages"
        ]
        Resource = aws_ecr_repository.app.arn
      }
    ]
  })
}

resource "aws_iam_access_key" "github_actions" {
  user = aws_iam_user.github_actions.name
}

# ── SSM Parameter Store placeholders ─────────────────────────────────────────
# These are created here as SecureString placeholders.
# Populate the actual values via the AWS console or:
#   aws ssm put-parameter --name /backlog-synthesizer/ANTHROPIC_API_KEY \
#     --value "sk-ant-..." --type SecureString --overwrite
#
# Terraform stores the value in state — set sensitive = true and use a
# placeholder here; update via CLI to avoid leaking secrets into state.

resource "aws_ssm_parameter" "anthropic_api_key" {
  name        = "/backlog-synthesizer/ANTHROPIC_API_KEY"
  description = "Anthropic API key for Claude"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_VIA_CLI"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "backlog-synthesizer-anthropic-key"
  }
}

resource "aws_ssm_parameter" "jira_api_token" {
  name        = "/backlog-synthesizer/JIRA_API_TOKEN"
  description = "Atlassian API token for Jira/Confluence"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_VIA_CLI"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "backlog-synthesizer-jira-token"
  }
}

resource "aws_ssm_parameter" "google_api_key" {
  name        = "/backlog-synthesizer/GOOGLE_API_KEY"
  description = "Google API key for Gemini (optional)"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_VIA_CLI"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "backlog-synthesizer-google-key"
  }
}
