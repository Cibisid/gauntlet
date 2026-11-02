variable "name_prefix" {
  description = "Prefix for resource names, e.g. \"gauntlet-staging\"."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module (in addition to provider default_tags)."
  type        = map(string)
  default     = {}
}

# --- k3s node ---------------------------------------------------------------

variable "k3s_instance_type" {
  description = "EC2 instance type for the single-node k3s server. t3.medium (2 vCPU, 4 GiB) is the smallest comfortable size for k3s plus the gauntlet services."
  type        = string
  default     = "t3.medium"

  validation {
    condition     = can(regex("^(t3|t3a|t4g|m6i|m6a|m7i|m7a|m7g|c6i|c7i)\\.(medium|large|xlarge)$", var.k3s_instance_type))
    error_message = "k3s_instance_type must be a general-purpose type between medium and xlarge (e.g. t3.medium, t3a.medium, t3.large). Graviton (t4g/m7g) also needs an arm64 k3s_ami_ssm_parameter."
  }
}

variable "k3s_ami_ssm_parameter" {
  description = "Public SSM parameter that resolves to the k3s node AMI ID. Default: latest Amazon Linux 2023 x86_64."
  type        = string
  default     = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

variable "k3s_version" {
  description = "Pinned k3s release passed to INSTALL_K3S_VERSION (see https://github.com/k3s-io/k3s/releases)."
  type        = string
  default     = "v1.31.4+k3s1"

  validation {
    condition     = can(regex("^v1\\.[0-9]+\\.[0-9]+\\+k3s[0-9]+$", var.k3s_version))
    error_message = "k3s_version must look like v1.31.4+k3s1."
  }
}

variable "k3s_root_volume_gb" {
  description = "Size of the encrypted gp3 root volume for the k3s node, in GiB."
  type        = number
  default     = 30

  validation {
    condition     = var.k3s_root_volume_gb >= 20 && var.k3s_root_volume_gb <= 200
    error_message = "k3s_root_volume_gb must be between 20 and 200."
  }
}

variable "k3s_termination_protection" {
  description = "Enable EC2 API termination protection on the k3s node. Must be set to false (and applied) before `terraform destroy`."
  type        = bool
  default     = false
}

variable "k3s_subnet_id" {
  description = "Subnet ID for the k3s node."
  type        = string
}

variable "k3s_security_group_id" {
  description = "Security group ID for the k3s node."
  type        = string
}

variable "ecr_repository_arn" {
  description = "ARN of the ECR repository the k3s node may pull from."
  type        = string
}

variable "results_bucket_arn" {
  description = "ARN of the eval results bucket the k3s node may read and write."
  type        = string
}

variable "k3s_secret_arns" {
  description = "Secrets Manager secret ARNs the k3s node may read (provider API key, gateway admin key)."
  type        = list(string)

  validation {
    condition     = length(var.k3s_secret_arns) > 0 && alltrue([for a in var.k3s_secret_arns : can(regex("^arn:aws[a-z-]*:secretsmanager:", a))])
    error_message = "k3s_secret_arns must be a non-empty list of Secrets Manager ARNs (no wildcards)."
  }
}

variable "ebs_kms_key_arn" {
  description = "Optional customer-managed KMS key ARN for EBS root volumes. null uses the AWS-managed aws/ebs key (no monthly key fee)."
  type        = string
  default     = null
}

# --- GPU / vLLM node ----------------------------------------------------------

variable "enable_gpu" {
  description = "Create the GPU spot instance running vLLM. Turn on only for benchmark windows."
  type        = bool
  default     = false
}

variable "gpu_instance_type" {
  description = "GPU instance type for vLLM: g6.xlarge (NVIDIA L4, 24 GB) or g5.xlarge (NVIDIA A10G, 24 GB)."
  type        = string
  default     = "g6.xlarge"

  validation {
    condition     = contains(["g6.xlarge", "g6.2xlarge", "g5.xlarge", "g5.2xlarge"], var.gpu_instance_type)
    error_message = "gpu_instance_type must be one of g6.xlarge, g6.2xlarge, g5.xlarge, g5.2xlarge."
  }
}

variable "gpu_ami_ssm_parameter" {
  description = "Public SSM parameter that resolves to a GPU AMI with NVIDIA driver, Docker and the NVIDIA container toolkit. Default: AWS Deep Learning Base OSS Nvidia Driver GPU AMI (Amazon Linux 2023)."
  type        = string
  default     = "/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-amazon-linux-2023/latest/ami-id"
}

variable "gpu_subnet_id" {
  description = "Subnet ID for the GPU spot instance (pick the AZ with spot capacity)."
  type        = string
  default     = null
}

variable "gpu_security_group_id" {
  description = "Security group ID for the GPU spot instance."
  type        = string
  default     = null
}

variable "gpu_root_volume_gb" {
  description = "Size of the encrypted gp3 root volume for the GPU node, in GiB (vLLM image plus model weights)."
  type        = number
  default     = 100

  validation {
    condition     = var.gpu_root_volume_gb >= 60 && var.gpu_root_volume_gb <= 500
    error_message = "gpu_root_volume_gb must be between 60 and 500."
  }
}

variable "gpu_spot_max_price" {
  description = "Optional maximum spot price in USD per hour (string, e.g. \"0.50\"). null caps at the on-demand price."
  type        = string
  default     = null

  validation {
    condition     = var.gpu_spot_max_price == null || can(tonumber(var.gpu_spot_max_price))
    error_message = "gpu_spot_max_price must be null or a numeric string such as \"0.50\"."
  }
}

variable "gpu_max_runtime_hours" {
  description = "Hours after boot at which the GPU instance shuts itself down (and terminates). Cost backstop for forgotten benchmark windows."
  type        = number
  default     = 4

  validation {
    condition     = var.gpu_max_runtime_hours >= 1 && var.gpu_max_runtime_hours <= 24 && floor(var.gpu_max_runtime_hours) == var.gpu_max_runtime_hours
    error_message = "gpu_max_runtime_hours must be a whole number between 1 and 24."
  }
}

variable "vllm_image" {
  description = "vLLM OpenAI-compatible server image, pinned to a tag (or better, a digest)."
  type        = string
  default     = "vllm/vllm-openai:v0.6.6"

  validation {
    condition     = can(regex("[:@]", var.vllm_image)) && !endswith(var.vllm_image, ":latest")
    error_message = "vllm_image must be pinned to a tag or digest, not :latest."
  }
}

variable "vllm_model" {
  description = "Hugging Face model ID served by vLLM. Must fit in 24 GB GPU memory (e.g. a 7-8B model in bf16). Gated models also need a Hugging Face token, which this module does not configure."
  type        = string
  default     = "Qwen/Qwen2.5-7B-Instruct"

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$", var.vllm_model))
    error_message = "vllm_model must be a Hugging Face model ID like org/name."
  }
}

variable "vllm_max_model_len" {
  description = "Maximum context length passed to vLLM (--max-model-len); lower it if the KV cache does not fit."
  type        = number
  default     = 8192

  validation {
    condition     = var.vllm_max_model_len >= 512 && var.vllm_max_model_len <= 131072
    error_message = "vllm_max_model_len must be between 512 and 131072."
  }
}

variable "vllm_port" {
  description = "Host port the vLLM server is published on. Must match the network module's vllm_port."
  type        = number
  default     = 8000
}

variable "enable_vllm_api_key" {
  description = "Require an API key on the vLLM server, read at boot from vllm_api_key_secret_arn. A plain boolean so instance counts are known at plan time."
  type        = bool
  default     = true
}

variable "vllm_api_key_secret_arn" {
  description = "Secrets Manager ARN holding the vLLM API key (required when enable_vllm_api_key = true). The GPU role may read only this secret."
  type        = string
  default     = null
}
