output "raw_bucket_name" {
  value = aws_s3_bucket.raw.bucket
}

output "warn_source_state_table_name" {
  value = aws_dynamodb_table.source_state.name
}

output "warn_notices_table_name" {
  value = aws_dynamodb_table.notices.name
}

output "watchlists_table_name" {
  value = aws_dynamodb_table.watchlists.name
}

output "notifications_table_name" {
  value = aws_dynamodb_table.notifications.name
}

output "ingest_lambda_name" {
  value = aws_lambda_function.ingest.function_name
}

output "match_notify_lambda_name" {
  value = aws_lambda_function.matcher.function_name
}

output "scheduler_name" {
  value = aws_scheduler_schedule.ingest.name
}

output "sns_topic_arn" {
  value = aws_sns_topic.new_notice.arn
}

output "watchlist_api_lambda_name" {
  value = aws_lambda_function.watchlist_api.function_name
}

output "web_bucket_name" {
  value = aws_s3_bucket.web.bucket
}

output "cloudfront_distribution_domain_name" {
  value = aws_cloudfront_distribution.web.domain_name
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.web.id
}

output "frontend_url" {
  value = var.enable_custom_domains ? "https://${var.root_domain}" : "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "watchlist_api_default_endpoint" {
  value = aws_apigatewayv2_api.watchlist.api_endpoint
}

output "watchlist_api_subscribe_default_url" {
  value = "${aws_apigatewayv2_api.watchlist.api_endpoint}/subscribe"
}

output "watchlist_api_custom_domain_name" {
  value = var.enable_custom_domains ? aws_apigatewayv2_domain_name.watchlist_api[0].domain_name : null
}

output "watchlist_api_custom_domain_target" {
  value = var.enable_custom_domains ? aws_apigatewayv2_domain_name.watchlist_api[0].domain_name_configuration[0].target_domain_name : null
}

output "web_certificate_dns_validation_records" {
  value = [
    for dvo in aws_acm_certificate.web.domain_validation_options : {
      domain_name  = dvo.domain_name
      record_name  = dvo.resource_record_name
      record_type  = dvo.resource_record_type
      record_value = dvo.resource_record_value
    }
  ]
}

output "api_certificate_dns_validation_records" {
  value = [
    for dvo in aws_acm_certificate.api.domain_validation_options : {
      domain_name  = dvo.domain_name
      record_name  = dvo.resource_record_name
      record_type  = dvo.resource_record_type
      record_value = dvo.resource_record_value
    }
  ]
}

output "cloudflare_dns_targets" {
  value = {
    apex = aws_cloudfront_distribution.web.domain_name
    www  = aws_cloudfront_distribution.web.domain_name
    api  = var.enable_custom_domains ? aws_apigatewayv2_domain_name.watchlist_api[0].domain_name_configuration[0].target_domain_name : null
  }
}
