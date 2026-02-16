resource "aws_apigatewayv2_api" "watchlist" {
  name          = "${var.project_name}-watchlist-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = false
    allow_headers     = ["content-type"]
    allow_methods     = ["POST", "OPTIONS"]
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

resource "aws_apigatewayv2_stage" "watchlist_default" {
  api_id      = aws_apigatewayv2_api.watchlist.id
  name        = "$default"
  auto_deploy = true

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
