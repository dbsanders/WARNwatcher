resource "aws_apigatewayv2_api" "watchlist" {
  name          = "${var.project_name}-watchlist-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = false
    allow_headers     = ["content-type", "authorization"]
    allow_methods     = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_origins     = ["https://${var.root_domain}", "https://${local.www_domain_name}"]
    max_age           = 3600
  }

  tags = local.tags
}

resource "aws_apigatewayv2_integration" "watchlist_lambda" {
  api_id                 = aws_apigatewayv2_api.watchlist.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.watchlist_api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "watchlist_subscribe" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "POST /subscribe"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_signup" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "POST /signup"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_login" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "POST /login"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_verify_email" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "POST /verify-email"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_resend_verification" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "POST /resend-verification"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_forgot_password" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "POST /forgot-password"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_reset_password" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "POST /reset-password"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_subscriptions_list" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "GET /subscriptions"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_notices_list" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "GET /notices"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_subscriptions_update" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "PUT /subscriptions/{watch_id}"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_route" "watchlist_subscriptions_delete" {
  api_id    = aws_apigatewayv2_api.watchlist.id
  route_key = "DELETE /subscriptions/{watch_id}"
  target    = "integrations/${aws_apigatewayv2_integration.watchlist_lambda.id}"
}

resource "aws_apigatewayv2_stage" "watchlist_default" {
  api_id      = aws_apigatewayv2_api.watchlist.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.watchlist_api_access.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      requestTimeEpoch = "$context.requestTimeEpoch"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
    })
  }

  dynamic "route_settings" {
    for_each = {
      "POST /signup"              = { rate = 2, burst = 5 }
      "POST /forgot-password"     = { rate = 2, burst = 5 }
      "POST /resend-verification" = { rate = 2, burst = 5 }
      "POST /login"               = { rate = 10, burst = 20 }
      "POST /verify-email"        = { rate = 5, burst = 10 }
      "POST /reset-password"      = { rate = 5, burst = 10 }
    }

    content {
      route_key              = route_settings.key
      throttling_rate_limit  = route_settings.value.rate
      throttling_burst_limit = route_settings.value.burst
    }
  }

  tags = local.tags
}

resource "aws_apigatewayv2_domain_name" "watchlist_api" {
  count       = var.enable_custom_domains ? 1 : 0
  domain_name = local.api_domain_name

  domain_name_configuration {
    certificate_arn = aws_acm_certificate.api.arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = local.tags
}

resource "aws_apigatewayv2_api_mapping" "watchlist_api" {
  count       = var.enable_custom_domains ? 1 : 0
  api_id      = aws_apigatewayv2_api.watchlist.id
  domain_name = aws_apigatewayv2_domain_name.watchlist_api[0].id
  stage       = aws_apigatewayv2_stage.watchlist_default.name
}
