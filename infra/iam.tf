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
    sid       = "PublishToSNS"
    actions   = ["sns:Publish"]
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
    sid       = "SesSend"
    actions   = ["ses:SendEmail"]
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

resource "aws_iam_role" "watchlist_api_lambda" {
  name               = "${var.project_name}-watchlist-api-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.tags
}

data "aws_iam_policy_document" "watchlist_api_policy" {
  statement {
    sid = "DynamoWatchlistsWrite"
    actions = [
      "dynamodb:PutItem"
    ]
    resources = [aws_dynamodb_table.watchlists.arn]
  }

  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["${aws_cloudwatch_log_group.watchlist_api.arn}:*"]
  }
}

resource "aws_iam_role_policy" "watchlist_api_policy" {
  name   = "${var.project_name}-watchlist-api-lambda-policy"
  role   = aws_iam_role.watchlist_api_lambda.id
  policy = data.aws_iam_policy_document.watchlist_api_policy.json
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
