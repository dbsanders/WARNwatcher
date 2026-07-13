data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 3
}

resource "random_password" "auth_token_secret" {
  length  = 48
  special = false
}

locals {
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }

  bucket_name             = lower("${var.project_name}-${data.aws_caller_identity.current.account_id}-${var.region}-${random_id.suffix.hex}")
  web_bucket_name         = lower("${var.project_name}-web-${data.aws_caller_identity.current.account_id}-${var.region}-${random_id.suffix.hex}")
  ingest_zip_path         = "${path.module}/../dist/ingest.zip"
  matcher_zip_path        = "${path.module}/../dist/match_notify.zip"
  monthly_digest_zip_path = "${path.module}/../dist/monthly_digest.zip"
  watchlist_api_zip_path  = "${path.module}/../dist/watchlist_api.zip"
  www_domain_name         = "${var.www_subdomain}.${var.root_domain}"
  api_domain_name         = "${var.api_subdomain}.${var.root_domain}"
}
