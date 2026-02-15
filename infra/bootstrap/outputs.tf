output "state_bucket_name" {
  value       = aws_s3_bucket.tf_state.bucket
  description = "S3 bucket name for Terraform state."
}

output "lock_table_name" {
  value       = aws_dynamodb_table.tf_lock.name
  description = "DynamoDB table name for Terraform state locking."
}

output "backend_region" {
  value       = var.region
  description = "AWS region for Terraform backend."
}
