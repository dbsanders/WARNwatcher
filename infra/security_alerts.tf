resource "aws_sns_topic" "security_alerts" {
  name = "${var.project_name}-security-alerts"
  tags = local.tags
}

data "aws_iam_policy_document" "security_alerts" {
  statement {
    sid       = "AllowCloudWatchSecurityAlarms"
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.security_alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.expected_account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudwatch:${var.region}:${var.expected_account_id}:alarm:${var.project_name}-*"]
    }
  }
}

resource "aws_sns_topic_policy" "security_alerts" {
  arn    = aws_sns_topic.security_alerts.arn
  policy = data.aws_iam_policy_document.security_alerts.json
}

resource "aws_sns_topic_subscription" "security_alert_email" {
  topic_arn = aws_sns_topic.security_alerts.arn
  protocol  = "email"
  endpoint  = var.default_alert_recipient_email
}

resource "aws_cloudwatch_log_metric_filter" "auth_rate_limited" {
  name           = "${var.project_name}-auth-rate-limited"
  log_group_name = aws_cloudwatch_log_group.watchlist_api.name
  pattern        = "{ $.event = \"rate_limit_exceeded\" }"

  metric_transformation {
    name          = "AuthRateLimited"
    namespace     = "${var.project_name}/Security"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "auth_rate_limit_error" {
  name           = "${var.project_name}-auth-rate-limit-error"
  log_group_name = aws_cloudwatch_log_group.watchlist_api.name
  pattern        = "{ $.event = \"rate_limit_error\" }"

  metric_transformation {
    name          = "AuthRateLimitError"
    namespace     = "${var.project_name}/Security"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "api_throttled" {
  name           = "${var.project_name}-api-throttled"
  log_group_name = aws_cloudwatch_log_group.watchlist_api_access.name
  pattern        = "{ $.status = \"429\" }"

  metric_transformation {
    name          = "ApiThrottled"
    namespace     = "${var.project_name}/Security"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "auth_rate_limited" {
  alarm_name          = "${var.project_name}-auth-rate-limited"
  alarm_description   = "Authentication requests exceeded an account or source limit at least 10 times in five minutes."
  namespace           = "${var.project_name}/Security"
  metric_name         = "AuthRateLimited"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.security_alerts.arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "auth_rate_limit_error" {
  alarm_name          = "${var.project_name}-auth-rate-limit-error"
  alarm_description   = "The authentication rate-limit store failed; requests fail closed."
  namespace           = "${var.project_name}/Security"
  metric_name         = "AuthRateLimitError"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.security_alerts.arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "api_throttled" {
  alarm_name          = "${var.project_name}-api-throttled"
  alarm_description   = "The API returned at least 10 HTTP 429 responses in five minutes."
  namespace           = "${var.project_name}/Security"
  metric_name         = "ApiThrottled"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.security_alerts.arn]
  tags                = local.tags
}
