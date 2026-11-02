# GitHub Actions -> AWS via OIDC: no long-lived AWS keys in CI (design §7).
#
# The role can be assumed only by workflows in `github_repository` running on
# the allowed branches (default: main) or for pull_request events. Its policy
# allows exactly two things: push images to one ECR repository, and write
# objects to one S3 bucket prefix.
#
# Note: GitHub does not issue OIDC tokens to pull_request runs from forks, so
# the pull_request subject only matches PRs from branches in the repository
# itself. Never use pull_request_target with this role.

locals {
  oidc_host = "token.actions.githubusercontent.com"

  allowed_subjects = concat(
    [for b in var.allowed_branches : "repo:${var.github_repository}:ref:refs/heads/${b}"],
    var.allow_pull_requests ? ["repo:${var.github_repository}:pull_request"] : [],
  )

  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

# Only one GitHub OIDC provider can exist per AWS account; reuse it if present.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url            = "https://${local.oidc_host}"
  client_id_list = ["sts.amazonaws.com"]
  # AWS validates GitHub's certificate against its own trusted CAs; these
  # thumbprints are kept for older provider versions that require the field.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]

  tags = merge(var.tags, { Name = "github-actions" })
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1

  url = "https://${local.oidc_host}"
}

data "aws_iam_policy_document" "trust" {
  statement {
    sid     = "GitHubActionsOidc"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Exact subjects only; no wildcards.
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = local.allowed_subjects
    }
  }
}

resource "aws_iam_role" "ci" {
  name                 = var.role_name
  description          = "GitHub Actions (${var.github_repository}) - push to ECR and write eval results"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600

  tags = var.tags
}

#tfsec:ignore:aws-iam-no-policy-wildcards -- only ecr:GetAuthorizationToken uses "*"; S3 resource is a single bucket prefix
data "aws_iam_policy_document" "ci" {
  #checkov:skip=CKV_AWS_111:ecr:GetAuthorizationToken does not support resource-level permissions; every other action is scoped to one repository or one bucket prefix.
  #checkov:skip=CKV_AWS_356:ecr:GetAuthorizationToken does not support resource-level permissions; every other action is scoped to one repository or one bucket prefix.
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:DescribeImageScanFindings",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [var.ecr_repository_arn]
  }

  statement {
    sid = "ResultsWrite"
    actions = [
      "s3:PutObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${var.results_bucket_arn}/${var.results_prefix}*"]
  }
}

resource "aws_iam_role_policy" "ci" {
  name   = "ecr-push-results-write"
  role   = aws_iam_role.ci.id
  policy = data.aws_iam_policy_document.ci.json
}
