resource "aws_dynamodb_table" "source_state" {
  name         = "${var.project_name}-warn-source-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "source_id"

  attribute {
    name = "source_id"
    type = "S"
  }

  tags = local.tags
}

resource "aws_dynamodb_table" "notices" {
  name         = "${var.project_name}-warn-notices"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "notice_id"

  attribute {
    name = "notice_id"
    type = "S"
  }

  tags = local.tags
}

resource "aws_dynamodb_table" "watchlists" {
  name         = "${var.project_name}-watchlists"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "watch_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "watch_id"
    type = "S"
  }

  tags = local.tags
}

resource "aws_dynamodb_table" "notifications" {
  name         = "${var.project_name}-notifications"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "notice_id"
  range_key    = "user_id"

  attribute {
    name = "notice_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  tags = local.tags
}
