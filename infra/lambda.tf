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
      PROJECT_NAME                  = var.project_name
      SOURCE_ID                     = "CA_WARN_XLSX"
      WARN_CA_URL                   = var.warn_ca_url
      RAW_BUCKET_NAME               = aws_s3_bucket.raw.bucket
      SOURCE_STATE_TABLE            = aws_dynamodb_table.source_state.name
      NOTICES_TABLE                 = aws_dynamodb_table.notices.name
      NEW_NOTICE_TOPIC_ARN          = aws_sns_topic.new_notice.arn
      DEFAULT_ALERT_RECIPIENT_EMAIL = var.default_alert_recipient_email
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
      PROJECT_NAME                  = var.project_name
      WATCHLISTS_TABLE              = aws_dynamodb_table.watchlists.name
      NOTIFICATIONS_TABLE           = aws_dynamodb_table.notifications.name
      ALERT_SENDER_EMAIL            = var.alert_sender_email
      DEFAULT_ALERT_RECIPIENT_EMAIL = var.default_alert_recipient_email
    }
  }

  depends_on = [aws_cloudwatch_log_group.matcher]
  tags       = local.tags
}

resource "aws_lambda_function" "watchlist_api" {
  function_name    = "${var.project_name}-watchlist-api"
  role             = aws_iam_role.watchlist_api_lambda.arn
  runtime          = "python3.11"
  handler          = "app.handler"
  filename         = local.watchlist_api_zip_path
  source_code_hash = filebase64sha256(local.watchlist_api_zip_path)
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      WATCHLISTS_TABLE          = aws_dynamodb_table.watchlists.name
      NOTICES_TABLE             = aws_dynamodb_table.notices.name
      NOTIFICATIONS_TABLE       = aws_dynamodb_table.notifications.name
      USERS_TABLE               = aws_dynamodb_table.users.name
      AUTH_TOKEN_SECRET         = random_password.auth_token_secret.result
      AUTH_TOKEN_TTL_SEC        = "86400"
      RESET_TOKEN_TTL_SEC       = "3600"
      ALERT_SENDER_EMAIL        = var.alert_sender_email
      PASSWORD_RESET_FROM_EMAIL = var.alert_sender_email
      WEB_APP_BASE_URL          = var.enable_custom_domains ? "https://${var.root_domain}" : "https://${aws_cloudfront_distribution.web.domain_name}"
      DEFAULT_STATE             = "CA"
    }
  }

  depends_on = [aws_cloudwatch_log_group.watchlist_api]
  tags       = local.tags
}

resource "aws_lambda_permission" "allow_apigw_watchlist_api" {
  statement_id  = "AllowExecutionFromApiGatewayWatchlist"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.watchlist_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.watchlist.execution_arn}/*/*"
}

resource "aws_lambda_permission" "allow_scheduler" {
  statement_id  = "AllowExecutionFromScheduler"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = aws_scheduler_schedule.ingest.arn
}
