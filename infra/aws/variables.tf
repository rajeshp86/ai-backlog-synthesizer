variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment tag"
  type        = string
  default     = "production"
}

variable "key_pair_name" {
  description = "EC2 key pair name for SSH access (must already exist in AWS)"
  type        = string
}

variable "ssh_allowed_cidr" {
  description = "CIDR allowed to SSH into the instance — restrict to your IP in production"
  type        = string
  default     = "0.0.0.0/0"
}

variable "app_port" {
  description = "Port the Streamlit UI listens on"
  type        = number
  default     = 8502
}

variable "instance_type" {
  description = "EC2 instance type — t2.micro is AWS free tier eligible"
  type        = string
  default     = "t2.micro"
}

variable "root_volume_size_gb" {
  description = "Root EBS volume size in GB (gp3)"
  type        = number
  default     = 20
}

variable "outputs_bucket_name" {
  description = "S3 bucket name for persistent synthesis outputs and embedding cache (must be globally unique)"
  type        = string
  default     = "backlog-synthesizer-outputs"
}
