# Write-only stretch goal. No terraform apply was run.
# Source: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_replication_configuration
# Existing buckets must be in independent regions. Versioning is enabled on both.
variable "source_bucket_name" {
  type = string
}
variable "destination_bucket_name" {
  type = string
}
variable "replication_role_arn" {
  type        = string
  description = "Existing S3-assumable IAM role with source read-version and destination replication permissions"
}
variable "source_region" {
  type = string
}
variable "destination_region" {
  type = string
}

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

provider "aws" {
  region = var.source_region
}
provider "aws" {
  alias  = "destination"
  region = var.destination_region
}

resource "aws_s3_bucket_versioning" "source" {
  bucket = var.source_bucket_name
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_s3_bucket_versioning" "destination" {
  provider = aws.destination
  bucket   = var.destination_bucket_name
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_replication_configuration" "artifacts" {
  depends_on = [aws_s3_bucket_versioning.source, aws_s3_bucket_versioning.destination]
  role       = var.replication_role_arn
  bucket     = var.source_bucket_name

  rule {
    id       = "ai-dr-artifacts"
    priority = 1
    status   = "Enabled"
    filter {
      prefix = ""
    }
    delete_marker_replication {
      status = "Disabled"
    }
    destination {
      bucket        = "arn:aws:s3:::${var.destination_bucket_name}"
      storage_class = "STANDARD"
    }
  }
}

# vectors.sqlite, model.bin and MANIFEST.json correspond to snapshot.put artifacts.
# Native versioning retains per-object historical versions; manifest must record
# their exact version IDs/checksums for a coherent restore. Independent replication
# of three mutable keys is not an atomic snapshot. Upload immutable snapshot prefixes,
# then publish a commit manifest and verify all referenced versions before get.
# IAM trust: s3.amazonaws.com; source ListBucket/GetReplicationConfiguration,
# GetObjectVersionForReplication/GetObjectVersionAcl/GetObjectVersionTagging;
# destination ReplicateObject/ReplicateTags. Cross-account policies and KMS need
# additional configuration. This draft assumes same-account non-KMS buckets.
