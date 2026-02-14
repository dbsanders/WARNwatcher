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
