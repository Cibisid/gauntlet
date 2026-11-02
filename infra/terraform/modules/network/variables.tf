variable "name_prefix" {
  description = "Prefix for resource names, e.g. \"gauntlet-staging\"."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name_prefix))
    error_message = "name_prefix must be 3-31 chars of lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the VPC. Subnets are carved as /24s (vpc_cidr + 8 bits)."
  type        = string
  default     = "10.40.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0)) && tonumber(split("/", var.vpc_cidr)[1]) <= 22
    error_message = "vpc_cidr must be a valid IPv4 CIDR with a prefix length of /22 or larger (e.g. 10.40.0.0/16)."
  }
}

variable "subnet_count" {
  description = "Number of public subnets (one per availability zone). Two gives the GPU spot instance a second AZ to try."
  type        = number
  default     = 2

  validation {
    condition     = var.subnet_count >= 1 && var.subnet_count <= 2
    error_message = "subnet_count must be 1 or 2."
  }
}

variable "admin_cidr" {
  description = "Single IPv4 CIDR allowed to reach ports 443 and 6443 (e.g. your home IP as x.x.x.x/32). 0.0.0.0/0 is rejected."
  type        = string

  validation {
    condition = (
      can(cidrhost(var.admin_cidr, 0)) &&
      can(tonumber(split("/", var.admin_cidr)[1])) &&
      try(tonumber(split("/", var.admin_cidr)[1]) >= 16, false)
    )
    error_message = "admin_cidr must be a valid IPv4 CIDR with a prefix of /16 or narrower (a /32 is recommended). 0.0.0.0/0 is not allowed."
  }
}

variable "vllm_port" {
  description = "TCP port the vLLM OpenAI-compatible server listens on, opened only from the k3s node to the GPU node."
  type        = number
  default     = 8000

  validation {
    condition     = var.vllm_port > 1024 && var.vllm_port < 65536
    error_message = "vllm_port must be an unprivileged port (1025-65535)."
  }
}

variable "enable_flow_logs" {
  description = "Create VPC flow logs to CloudWatch Logs."
  type        = bool
  default     = true
}

variable "flow_log_traffic_type" {
  description = "Which traffic flow logs capture: ACCEPT, REJECT or ALL. REJECT keeps volume (and cost) minimal."
  type        = string
  default     = "REJECT"

  validation {
    condition     = contains(["ACCEPT", "REJECT", "ALL"], var.flow_log_traffic_type)
    error_message = "flow_log_traffic_type must be ACCEPT, REJECT or ALL."
  }
}

variable "flow_log_retention_days" {
  description = "Retention for the flow log group, in days."
  type        = number
  default     = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365], var.flow_log_retention_days)
    error_message = "flow_log_retention_days must be a CloudWatch-supported value such as 7, 14, 30, 90 or 365."
  }
}

variable "tags" {
  description = "Tags applied to every resource in this module (in addition to provider default_tags)."
  type        = map(string)
  default     = {}
}

variable "availability_zones" {
  description = "Optional explicit list of availability zone names to pin subnets to (length must equal subnet_count). null uses the first subnet_count available zones."
  type        = list(string)
  default     = null

  validation {
    condition     = var.availability_zones == null || try(length(var.availability_zones) >= 1 && length(var.availability_zones) <= 2, false)
    error_message = "availability_zones must be null or a list of 1-2 zone names."
  }
}
