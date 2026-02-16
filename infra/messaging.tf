resource "aws_sns_topic" "new_notice" {
  name = "${var.project_name}-new-notice"
  tags = local.tags
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
