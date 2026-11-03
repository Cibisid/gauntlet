# Gauntlet on AWS (Terraform)

Terraform for a cheap, solo-developer AWS deployment of Gauntlet. It follows option (b) of [ADR-0003](../../docs/adr/0003-runtime-platform.md) and §10 of the [design doc](../../docs/design.md): an always-on single-node k3s staging cluster on one EC2 instance, plus an optional GPU spot instance that runs vLLM only during benchmark windows.

> **Status: not yet applied.** This code has not been run against a real AWS account. It passes `checkov` (see [Validation](#validation)), but `terraform validate`, `plan` and `apply` have not been run yet. Expect small fixes on the first apply.

## What gets created

| Module | Resources |
|---|---|
| `network` | VPC, 2 public subnets (no NAT gateway), internet gateway, VPC flow logs (rejected traffic), locked-down default security group, security groups for the k3s and GPU nodes |
| `compute` | t3.medium k3s node with an Elastic IP, IAM role and instance profile; optional GPU spot instance (`enable_gpu`) with its own role |
| `registry` | ECR repository `gauntlet`: immutable tags, scan on push, KMS encryption, keeps the last 10 images |
| `storage` | S3 results bucket: public access blocked, SSE-KMS, versioning, raw traces expire after 30 days, TLS-only policy |
| `secrets` | Secrets Manager placeholders (no values): provider API key, gateway admin key, vLLM API key |
| `ci_oidc` | GitHub Actions OIDC provider and a CI role for `Cibisid/gauntlet` (main branch and same-repo PRs only) |
| `budget` | Monthly AWS Budgets cost budget, email alerts at 50%, 80% and 100% of actual spend and at 100% of forecast |

`envs/staging` wires the modules together. Every resource is tagged `project=gauntlet`, `env=staging` and `managed_by=terraform`, through the provider's `default_tags` and the module `tags` inputs.

### Differences from the design doc

- **No RDS.** Design §10 lists RDS Postgres. For staging, Postgres is meant to run inside k3s on the node's encrypted disk. RDS (db.t4g.micro plus storage) would add roughly $15/month and can be added as a module later.
- **No EKS.** ADR-0003 option (a), short-lived EKS for demo windows, is not implemented here.
- **No Kubernetes workloads.** Terraform installs k3s and nothing else. Helm charts and manifests are deployed separately.

## Estimated monthly cost

These are rough us-east-1 on-demand list prices as I understood them when writing this. They were not fetched live, so check them with the [AWS Pricing Calculator](https://calculator.aws/) before relying on them.

Assumptions:

- The k3s node runs 24/7 (730 h/month) as an on-demand t3.medium with standard CPU credits.
- Storage is light: a few GB in ECR and S3.
- Data transfer out stays under the 100 GB/month free tier.
- The GPU runs only during benchmark windows. The example below is 4 windows of 4 hours a month.

| Item | Basis | ~USD/month |
|---|---|---|
| k3s node, t3.medium | $0.0416/h × 730 h | 30.40 |
| Root volume, 30 GB gp3 | $0.08/GB-month | 2.40 |
| Public IPv4 (Elastic IP) | $0.005/h × 730 h | 3.65 |
| Secrets Manager, 3 secrets | $0.40 each | 1.20 |
| ECR + S3 storage, a few GB | $0.10 / $0.023 per GB-month | < 0.50 |
| VPC flow logs (rejected only) | CloudWatch ingestion $0.50/GB | < 0.50 |
| KMS (AWS-managed keys), Budgets | AWS-managed keys and the first 2 budgets are free | 0.00 |
| NAT gateway | not created (would be about $33 plus data) | 0.00 |
| **Baseline, GPU off** | | **≈ 38** |
| GPU g6.xlarge spot, 16 h/month | about $0.35–0.50/h spot (on-demand $0.80/h) | 6–13 |
| GPU root volume, 100 GB gp3, 16 h | prorated | < 0.25 |
| **With benchmark windows** | | **≈ 44–51** |

What this means for the budget:

- The default `budget_usd = 40` sits just above the baseline, so the 80% alert will fire every month. Use `budget_usd = 50` if you run GPU windows.
- To cut the baseline instead:
  - `k3s_instance_type = "t3a.medium"` saves about $3/month.
  - Stopping the node when idle saves most of the compute cost, though the EIP and EBS volume still bill.
- `g5.xlarge` (A10G) costs about 25% more than `g6.xlarge` (L4).

## Prerequisites

- Terraform 1.6 or newer.
- AWS credentials for the target account, with an admin-like role for the first apply.
- The AWS CLI with the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html), for shell access.

## Apply

```bash
cd infra/terraform/envs/staging
cp terraform.tfvars.example terraform.tfvars   # set admin_cidr and alert_email
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

After applying:

1. **Set secret values.** Terraform never sees these values.

   ```bash
   aws secretsmanager put-secret-value --secret-id gauntlet-staging/provider-api-key --secret-string "$PROVIDER_KEY"
   aws secretsmanager put-secret-value --secret-id gauntlet-staging/gateway-admin-key --secret-string "$(openssl rand -hex 32)"
   aws secretsmanager put-secret-value --secret-id gauntlet-staging/vllm-api-key --secret-string "$(openssl rand -hex 32)"
   ```

2. **Get a shell or the kubeconfig.** Use `terraform output ssm_session_command` and `terraform output kubeconfig_command`. In the kubeconfig, replace `127.0.0.1` with `terraform output -raw k3s_public_ip`. The API on port 6443 only accepts connections from `admin_cidr`.

3. **Set up CI.** In GitHub Actions, use `aws-actions/configure-aws-credentials` with `role-to-assume: <ci_role_arn output>` and `permissions: id-token: write`.

   The role trusts only these exact subjects:
   - `repo:Cibisid/gauntlet:ref:refs/heads/main`
   - `repo:Cibisid/gauntlet:pull_request`

   A job that uses a GitHub `environment:` presents a different subject (`...:environment:<name>`), which would have to be added.

4. **Set up image pulls on the node.** The node role may pull from the ECR repo. k3s still needs a credential helper or a refreshed `imagePullSecret` for ECR, and this Terraform does not configure that.

The default backend is local state. To keep state in S3 with locking, see `envs/staging/backend.tf`.

### Running a GPU benchmark window

1. Run `terraform apply -var enable_gpu=true`. This creates a g6.xlarge spot instance from the AWS Deep Learning Base GPU AMI and starts `vllm/vllm-openai` serving `vllm_model`.
2. Wait a few minutes for the image pull and model download.
3. Point the gateway at `terraform output vllm_base_url`. The vLLM port is reachable only from the k3s node and requires the `vllm-api-key` secret as a bearer token.
4. When you are done, run `terraform apply -var enable_gpu=false`.

As a backstop, the instance shuts itself down and terminates `gpu_max_runtime_hours` (default 4) after boot. If that happens while `enable_gpu` is still true, the next plan will offer to recreate it, so set the variable back to false.

If spot capacity is unavailable, try `gpu_subnet_index = 1` (the other AZ) or `gpu_instance_type = "g5.xlarge"`.

## Destroy

```bash
cd infra/terraform/envs/staging
# The results bucket and ECR repo refuse deletion while they hold data.
# To tear everything down, including data:
terraform apply -var allow_destroy_with_data=true   # sets force_destroy/force_delete, 0-day secret recovery
terraform destroy -var allow_destroy_with_data=true
```

Without `allow_destroy_with_data`, empty the bucket (all versions) and the ECR repository first. Deleted secrets stay recoverable for 7 days by default. If you set `k3s_termination_protection = true` in the compute module, turn it off and apply before destroying.

## Security notes

- **No SSH.** There is no key pair and no port 22 rule. Shell access goes through SSM Session Manager, which is logged in CloudTrail.
- **Inbound** is only TCP 443 (ingress) and 6443 (Kubernetes API), and only from `admin_cidr`. `0.0.0.0/0` is rejected by validation. **Outbound** is TCP 443 only, plus k3s node → GPU node on the vLLM port.
- **IMDSv2 is required**, with hop limit 1, so pods and containers cannot read instance-role credentials.
- **Least-privilege IAM.**
  - The SSM permissions are written out instead of attaching `AmazonSSMManagedInstanceCore`.
  - The node role can pull from one ECR repo, read and write one bucket, and read two named secrets.
  - The GPU role can read only the vLLM key secret.
  - The CI role can push to one repo and write only under `ci/` in the bucket.
  - `Resource: "*"` appears only where AWS has no resource-level permissions (`ecr:GetAuthorizationToken`, `ssmmessages:*`, `ec2messages:*` actions). No action is a wildcard.
- **Encryption at rest:**
  - EBS: gp3 volumes encrypted with the aws/ebs key.
  - S3: SSE-KMS with the aws/s3 key and a bucket key.
  - ECR: KMS.
  - Secrets Manager: KMS.
  - k3s: Kubernetes Secrets encryption is on (`secrets-encryption: true`).

  These use AWS-managed keys to avoid the $1/month per customer-managed key. Every module accepts a `kms_key_arn` if you need a CMK.
- **In transit:** the bucket policy denies non-TLS requests and TLS below 1.2.
- **Data retention:** raw traces under `traces/raw/` expire after 30 days, and noncurrent versions expire too (design §7).
- **CI:** OIDC only, with no long-lived AWS keys. GitHub does not issue OIDC tokens to PRs from forks. Never grant this role to `pull_request_target` workflows.
- **State:** the state file holds resource IDs and the instance user data, but no secret values. Keep it in an encrypted, private S3 backend anyway.
- **TLS on 443:** Traefik serves a self-signed certificate by default. Let's Encrypt HTTP-01 needs port 80, which is closed, so use DNS-01 or bring your own certificate.
- **Pinned versions:** the k3s and vLLM image versions are pinned through variables. The k3s install script verifies the binary checksum. The AMIs track "latest" through public SSM parameters, and the k3s node ignores AMI changes so it is not replaced, so patch it with `dnf` / SSM Patch Manager.

### Accepted checkov / tfsec exceptions

Each one has an inline `#checkov:skip` / `#tfsec:ignore` comment with its reason.

| Check | Where | Why |
|---|---|---|
| CKV_AWS_88 | both instances | public IP needed because there is no NAT gateway (cost) |
| CKV_AWS_126 | both instances | detailed monitoring costs extra |
| CKV_AWS_111 / CKV_AWS_356 | IAM policy documents | `ecr:GetAuthorizationToken` and SSM channel actions need `"*"` |
| CKV_AWS_18, CKV_AWS_144, CKV2_AWS_62 | results bucket | access logging, cross-region replication and event notifications are cost or no consumer |
| CKV_AWS_149, CKV2_AWS_57 | secrets | AWS-managed key; third-party keys rotated manually |
| CKV_AWS_158, CKV_AWS_338 | flow log group | service-managed encryption, 30-day retention |
| CKV2_AWS_5 | security groups | attached in the compute module (cross-module) |
| CKV_AWS_394 | AZ data source | `availability_zones` variable pins zones when needed |

## Validation

What has been run so far:

- `checkov -d infra/terraform` (checkov 3.4.2): 177 passed, 0 failed, 20 skipped. The skips are the exceptions listed above.
- `terraform fmt`, `terraform validate`, `plan` and `apply`: **not run yet.** The Terraform binary could not be downloaded in the authoring environment.

Before the first apply, run:

```bash
terraform fmt -recursive -check infra/terraform
cd infra/terraform/envs/staging && terraform init -backend=false && terraform validate
```

## Layout

```
infra/terraform/
├── envs/staging/        # main.tf, variables.tf, outputs.tf, versions.tf, backend.tf, terraform.tfvars.example
└── modules/
    ├── network/  compute/ (templates/: k3s and vLLM user data)
    ├── registry/ storage/ secrets/
    └── ci_oidc/  budget/
```
