resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${var.project_name}-ingest"
  retention_in_days = 14
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "matcher" {
  name              = "/aws/lambda/${var.project_name}-match-notify"
  retention_in_days = 14
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "monthly_digest" {
  name              = "/aws/lambda/${var.project_name}-monthly-digest"
  retention_in_days = 14
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "watchlist_api" {
  name              = "/aws/lambda/${var.project_name}-watchlist-api"
  retention_in_days = 14
  tags              = local.tags
}
