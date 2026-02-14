data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 3
}

locals {
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }

  bucket_name      = lower("${var.project_name}-${data.aws_caller_identity.current.account_id}-${var.region}-${random_id.suffix.hex}")
  ingest_zip_path  = "${path.module}/../dist/ingest.zip"
  matcher_zip_path = "${path.module}/../dist/match_notify.zip"
}

resource "aws_s3_bucket" "raw" {
  bucket = local.bucket_name
  tags   = local.tags
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_dynamodb_table" "source_state" {
  name         = "${var.project_name}-warn-source-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "source_id"

  attribute {
    name = "source_id"
    type = "S"
  }

  tags = local.tags
}

resource "aws_dynamodb_table" "notices" {
  name         = "${var.project_name}-warn-notices"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "notice_id"

  attribute {
    name = "notice_id"
    type = "S"
  }

  tags = local.tags
}

resource "aws_dynamodb_table" "watchlists" {
  name         = "${var.project_name}-watchlists"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "watch_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "watch_id"
    type = "S"
  }

  tags = local.tags
}

resource "aws_dynamodb_table" "notifications" {
  name         = "${var.project_name}-notifications"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "notice_id"
  range_key    = "user_id"

  attribute {
    name = "notice_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  tags = local.tags
}

resource "aws_sns_topic" "new_notice" {
  name = "${var.project_name}-new-notice"
  tags = local.tags
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest_lambda" {
  name               = "${var.project_name}-ingest-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.tags
}

data "aws_iam_policy_document" "ingest_policy" {
  statement {
    sid = "S3Access"
    actions = [
      "s3:PutObject",
      "s3:GetObject"
    ]
    resources = ["${aws_s3_bucket.raw.arn}/*"]
  }

  statement {
    sid = "DynamoSourceState"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem"
    ]
    resources = [aws_dynamodb_table.source_state.arn]
  }

  statement {
    sid = "DynamoNotices"
    actions = [
      "dynamodb:PutItem"
    ]
    resources = [aws_dynamodb_table.notices.arn]
  }

  statement {
    sid = "PublishToSNS"
    actions = ["sns:Publish"]
    resources = [aws_sns_topic.new_notice.arn]
  }

  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["${aws_cloudwatch_log_group.ingest.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ingest_policy" {
  name   = "${var.project_name}-ingest-lambda-policy"
  role   = aws_iam_role.ingest_lambda.id
  policy = data.aws_iam_policy_document.ingest_policy.json
}

resource "aws_iam_role" "matcher_lambda" {
  name               = "${var.project_name}-matcher-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.tags
}

data "aws_iam_policy_document" "matcher_policy" {
  statement {
    sid = "DynamoWatchlistsRead"
    actions = [
      "dynamodb:Scan"
    ]
    resources = [aws_dynamodb_table.watchlists.arn]
  }

  statement {
    sid = "DynamoNotificationsWrite"
    actions = [
      "dynamodb:PutItem"
    ]
    resources = [aws_dynamodb_table.notifications.arn]
  }

  statement {
    sid = "SesSend"
    actions = ["ses:SendEmail"]
    resources = ["*"]
  }

  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["${aws_cloudwatch_log_group.matcher.arn}:*"]
  }
}

resource "aws_iam_role_policy" "matcher_policy" {
  name   = "${var.project_name}-matcher-lambda-policy"
  role   = aws_iam_role.matcher_lambda.id
  policy = data.aws_iam_policy_document.matcher_policy.json
}

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

resource "aws_lambda_function" "ingest" {
  function_name    = "${var.project_name}-ingest"
  role             = aws_iam_role.ingest_lambda.arn
  runtime          = "python3.11"
  handler          = "app.handler"
  filename         = local.ingest_zip_path
  source_code_hash = filebase64sha256(local.ingest_zip_path)
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      PROJECT_NAME                   = var.project_name
      SOURCE_ID                      = "CA_WARN_XLSX"
      WARN_CA_URL                    = var.warn_ca_url
      RAW_BUCKET_NAME                = aws_s3_bucket.raw.bucket
      SOURCE_STATE_TABLE             = aws_dynamodb_table.source_state.name
      NOTICES_TABLE                  = aws_dynamodb_table.notices.name
      NEW_NOTICE_TOPIC_ARN           = aws_sns_topic.new_notice.arn
      DEFAULT_ALERT_RECIPIENT_EMAIL  = var.default_alert_recipient_email
    }
  }

  depends_on = [aws_cloudwatch_log_group.ingest]
  tags       = local.tags
}

resource "aws_lambda_function" "matcher" {
  function_name    = "${var.project_name}-match-notify"
  role             = aws_iam_role.matcher_lambda.arn
  runtime          = "python3.11"
  handler          = "app.handler"
  filename         = local.matcher_zip_path
  source_code_hash = filebase64sha256(local.matcher_zip_path)
  timeout          = 120
  memory_size      = 256

  environment {
    variables = {
      PROJECT_NAME                   = var.project_name
      WATCHLISTS_TABLE               = aws_dynamodb_table.watchlists.name
      NOTIFICATIONS_TABLE            = aws_dynamodb_table.notifications.name
      ALERT_SENDER_EMAIL             = var.alert_sender_email
      DEFAULT_ALERT_RECIPIENT_EMAIL  = var.default_alert_recipient_email
    }
  }

  depends_on = [aws_cloudwatch_log_group.matcher]
  tags       = local.tags
}

resource "aws_sns_topic_subscription" "matcher_subscription" {
  topic_arn = aws_sns_topic.new_notice.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.matcher.arn
}

resource "aws_lambda_permission" "allow_sns" {
  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.matcher.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.new_notice.arn
}

data "aws_iam_policy_document" "scheduler_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler_invoke" {
  name               = "${var.project_name}-scheduler-invoke-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role.json
  tags               = local.tags
}

data "aws_iam_policy_document" "scheduler_invoke_policy" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.ingest.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke_policy" {
  name   = "${var.project_name}-scheduler-invoke-policy"
  role   = aws_iam_role.scheduler_invoke.id
  policy = data.aws_iam_policy_document.scheduler_invoke_policy.json
}

resource "aws_scheduler_schedule_group" "this" {
  name = "${var.project_name}-group"
  tags = local.tags
}

resource "aws_scheduler_schedule" "ingest" {
  name       = "${var.project_name}-ingest-schedule"
  group_name = aws_scheduler_schedule_group.this.name

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "America/Los_Angeles"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.ingest.arn
    role_arn = aws_iam_role.scheduler_invoke.arn
    input    = jsonencode({ force = false })
  }
}

resource "aws_lambda_permission" "allow_scheduler" {
  statement_id  = "AllowExecutionFromScheduler"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = aws_scheduler_schedule.ingest.arn
}
