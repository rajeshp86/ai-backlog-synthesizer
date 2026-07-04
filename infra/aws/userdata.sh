#!/bin/bash
# EC2 bootstrap — runs once at first launch as root.
# Installs Docker, pulls the app image from ECR, and starts it.
set -euo pipefail

LOG=/var/log/backlog-synthesizer-init.log
exec > >(tee -a "$LOG") 2>&1

echo "=== Backlog Synthesizer bootstrap $(date) ==="

# ── System packages ───────────────────────────────────────────────────────────
dnf update -y
# aws-cli v2 is pre-installed on AL2023 AMIs — do not add it here
dnf install -y docker curl

systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user

# ── App directories ───────────────────────────────────────────────────────────
mkdir -p /opt/backlog-synthesizer/{outputs,logs}
chown -R ec2-user:ec2-user /opt/backlog-synthesizer

# ── Pull secrets from SSM Parameter Store ─────────────────────────────────────
SSM_PREFIX="${ssm_prefix}"
REGION="${aws_region}"

get_param() {
  aws ssm get-parameter \
    --name "$SSM_PREFIX/$1" \
    --with-decryption \
    --query Parameter.Value \
    --output text \
    --region "$REGION" 2>/dev/null || echo ""
}

ANTHROPIC_API_KEY=$(get_param ANTHROPIC_API_KEY)
GOOGLE_API_KEY=$(get_param GOOGLE_API_KEY)
JIRA_API_TOKEN=$(get_param JIRA_API_TOKEN)

# ── Write .env file ───────────────────────────────────────────────────────────
cat > /opt/backlog-synthesizer/.env << EOF
# Populated by EC2 bootstrap from SSM Parameter Store
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
GOOGLE_API_KEY=$GOOGLE_API_KEY
JIRA_API_TOKEN=$JIRA_API_TOKEN

# App configuration
JIRA_MODE=mock
CONFLUENCE_MODE=mock
AUTH_DISABLED=1
LOG_FORMAT=json
OUTPUTS_DIR=/app/outputs
LOGS_DIR=/app/logs
AUDIT_DB_PATH=/app/logs/audit_chain.db
MAX_CONCURRENT_SYNTHESES=2

# S3 sync target (optional — mount via bind if needed)
S3_BUCKET=${s3_bucket}
AWS_REGION=${aws_region}
EOF

chmod 600 /opt/backlog-synthesizer/.env

# ── ECR login and pull ────────────────────────────────────────────────────────
ECR_REPO="${ecr_repo_url}"
ECR_REGISTRY=$(echo "$ECR_REPO" | cut -d/ -f1)

# ── Systemd service for auto-restart on reboot ────────────────────────────────
cat > /etc/systemd/system/backlog-synthesizer.service << EOF
[Unit]
Description=Backlog Synthesizer (Streamlit)
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=10
ExecStartPre=-/usr/bin/docker stop backlog-synthesizer
ExecStartPre=-/usr/bin/docker rm backlog-synthesizer
ExecStart=/usr/bin/docker run --rm \
  --name backlog-synthesizer \
  -p ${app_port}:8502 \
  --env-file /opt/backlog-synthesizer/.env \
  -v /opt/backlog-synthesizer/outputs:/app/outputs \
  -v /opt/backlog-synthesizer/logs:/app/logs \
  $ECR_REPO:latest
ExecStop=/usr/bin/docker stop backlog-synthesizer

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable backlog-synthesizer

# Try to pull and start the image now; if ECR is empty (first deploy),
# the service will start automatically once GitHub Actions pushes the image.
echo "Attempting initial ECR pull: $ECR_REPO:latest"
if aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "$ECR_REGISTRY" 2>/dev/null \
   && docker pull "$ECR_REPO:latest" 2>/dev/null; then
  systemctl start backlog-synthesizer
  echo "=== Bootstrap complete. App starting on port ${app_port} ==="
else
  echo "=== ECR image not available yet — service will start after first GitHub Actions deploy ==="
  echo "=== Run the cd-aws workflow in GitHub Actions to push the initial image ==="
fi
