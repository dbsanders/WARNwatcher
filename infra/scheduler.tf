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
