variable "project_name" {
  type        = string
  description = "Project name prefix for resources."
  default     = "WARNwatcher"
}

variable "region" {
  type        = string
  description = "AWS region."
  default     = "us-west-2"
}

variable "alert_sender_email" {
  type        = string
  description = "SES verified sender email."
  default     = "bret@warnwatcher.com"
}

variable "default_alert_recipient_email" {
  type        = string
  description = "Default recipient for MVP if watchlist email is missing."
  default     = "bret@cybersand.com"
}

variable "schedule_expression" {
  type        = string
  description = "EventBridge Scheduler expression."
  default     = "cron(15 9 ? * TUE,THU *)"
}

variable "warn_ca_url" {
  type        = string
  description = "California WARN XLSX URL."
  default     = "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report.xlsx"
}
