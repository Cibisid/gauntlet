# S3 bucket for eval results, gate reports and (PII-redacted) raw traces.
#   - all public access blocked, ACLs disabled (bucket owner enforced)
#   - default encryption: SSE-KMS with the AWS-managed aws/s3 key and an S3
#     bucket key (no monthly key fee, few KMS requests), or SSE-S3
#   - versioning on; old versions expire
#   - raw traces under `raw_traces_prefix` expire after `raw_trace_expiry_days`
#     (design §7: retention limits on stored traces)
#   - bucket policy denies non-TLS requests and TLS < 1.2

data "aws_caller_identity" "current" {}

locals {
  # Bucket names are global; suffix with the account ID to avoid collisions.
  bucket_name = coalesce(var.bucket_name, "${var.name_prefix}-results-${data.aws_caller_identity.current.account_id}")
}

#tfsec:ignore:aws-s3-enable-bucket-logging -- see checkov CKV_AWS_18 skip below
resource "aws_s3_bucket" "results" {
  #checkov:skip=CKV_AWS_18:Server access logging needs a second bucket and adds cost; CloudTrail data events can be enabled if an audit trail is needed.
  #checkov:skip=CKV_AWS_144:Cross-region replication doubles storage cost; results are reproducible from git-pinned releases and case sets.
  #checkov:skip=CKV2_AWS_62:No consumer for S3 event notifications in staging.
  bucket        = local.bucket_name
  force_destroy = var.force_destroy

  tags = merge(var.tags, { Name = local.bucket_name })
}

resource "aws_s3_bucket_ownership_controls" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "results" {
  bucket = aws_s3_bucket.results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "results" {
  bucket = aws_s3_bucket.results.id

  versioning_configuration {
    status = "Enabled"
  }
}

#tfsec:ignore:aws-s3-encryption-customer-key -- SSE-KMS with the AWS-managed aws/s3 key by default; kms_key_arn allows a CMK
resource "aws_s3_bucket_server_side_encryption_configuration" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.sse_algorithm
      kms_master_key_id = var.sse_algorithm == "aws:kms" ? var.kms_key_arn : null
    }
    bucket_key_enabled = var.sse_algorithm == "aws:kms"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "results" {
  bucket = aws_s3_bucket.results.id

  # Lifecycle rules act on versions, so make sure versioning exists first.
  depends_on = [aws_s3_bucket_versioning.results]

  rule {
    id     = "expire-raw-traces"
    status = "Enabled"

    filter {
      prefix = var.raw_traces_prefix
    }

    expiration {
      days = var.raw_trace_expiry_days
    }

    # Versioning would otherwise keep deleted traces around indefinitely.
    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  rule {
    id     = "bucket-hygiene"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiry_days
    }

    expiration {
      expired_object_delete_marker = true
    }
  }
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.results.arn,
      "${aws_s3_bucket.results.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid     = "DenyOutdatedTls"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.results.arn,
      "${aws_s3_bucket.results.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "NumericLessThan"
      variable = "s3:TlsVersion"
      values   = ["1.2"]
    }
  }
}

resource "aws_s3_bucket_policy" "results" {
  bucket = aws_s3_bucket.results.id
  policy = data.aws_iam_policy_document.tls_only.json

  # Avoid a race where the policy is evaluated before public access is blocked.
  depends_on = [aws_s3_bucket_public_access_block.results]
}
