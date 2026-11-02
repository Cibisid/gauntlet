variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.region))
    error_message = "region must be an AWS region code such as us-east-1."
  }
}

variable "admin_cidr" {
  description = "Your IPv4 address as a CIDR (e.g. 203.0.113.7/32). The only source allowed to reach the k3s node on 443 and 6443."
  type        = string
  # Format and width are validated in the network module (/16 or narrower, never 0.0.0.0/0).
}

variable "alert_email" {
  description = "Email address that receives AWS Budgets alerts."
  type        = string
}

variable "budget_usd" {
  description = "Monthly cost budget in USD; alerts at 50%, 80% and 100% of actual spend plus 100% forecast."
  type        = number
  default     = 40
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to assume the CI role."
  type        = string
  default     = "Cibisid/gauntlet"
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub Actions OIDC provider. Set false if this AWS account already has one."
  type        = bool
  default     = true
}

# --- network ----------------------------------------------------------------

variable "vpc_cidr" {
  description = "VPC CIDR block."
  type        = string
  default     = "10.40.0.0/16"
}

variable "subnet_count" {
  description = "Number of public subnets/AZs (1 or 2). Two gives GPU spot requests a second AZ."
  type        = number
  default     = 2
}

variable "enable_flow_logs" {
  description = "Enable VPC flow logs (rejected traffic) to CloudWatch Logs."
  type        = bool
  default     = true
}

# --- k3s node ---------------------------------------------------------------

variable "k3s_instance_type" {
  description = "Instance type for the always-on single-node k3s server."
  type        = string
  default     = "t3.medium"
}

variable "k3s_version" {
  description = "Pinned k3s version."
  type        = string
  default     = "v1.31.4+k3s1"
}

variable "k3s_root_volume_gb" {
  description = "Encrypted gp3 root volume size for the k3s node, in GiB."
  type        = number
  default     = 30
}

# --- GPU / vLLM ---------------------------------------------------------------

variable "enable_gpu" {
  description = "Create the GPU spot instance running vLLM. Leave false except during benchmark windows."
  type        = bool
  default     = false
}

variable "gpu_instance_type" {
  description = "GPU instance type: g6.xlarge (L4) or g5.xlarge (A10G)."
  type        = string
  default     = "g6.xlarge"
}

variable "gpu_subnet_index" {
  description = "Index into the public subnets for the GPU node; change it if one AZ has no spot capacity."
  type        = number
  default     = 0

  validation {
    condition     = var.gpu_subnet_index >= 0 && var.gpu_subnet_index <= 1
    error_message = "gpu_subnet_index must be 0 or 1."
  }
}

variable "gpu_max_runtime_hours" {
  description = "The GPU instance shuts down and terminates itself this many hours after boot."
  type        = number
  default     = 4
}

variable "gpu_spot_max_price" {
  description = "Optional spot price cap in USD/hour as a string (e.g. \"0.60\"); null caps at on-demand."
  type        = string
  default     = null
}

variable "vllm_image" {
  description = "Pinned vLLM OpenAI server image."
  type        = string
  default     = "vllm/vllm-openai:v0.6.6"
}

variable "vllm_model" {
  description = "Hugging Face model ID served by vLLM (ungated, fits in 24 GB)."
  type        = string
  default     = "Qwen/Qwen2.5-7B-Instruct"
}

variable "vllm_port" {
  description = "Port of the vLLM server, reachable only from the k3s node."
  type        = number
  default     = 8000
}

# --- data lifecycle -------------------------------------------------------------

variable "raw_trace_expiry_days" {
  description = "Days after which raw traces in the results bucket expire."
  type        = number
  default     = 30
}

variable "allow_destroy_with_data" {
  description = "Let `terraform destroy` remove the non-empty S3 bucket and ECR repository and delete secrets without a recovery window. Set true only for a full teardown."
  type        = bool
  default     = false
}
