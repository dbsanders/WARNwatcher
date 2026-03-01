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
  default     = "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx"
}

variable "root_domain" {
  type        = string
  description = "Apex domain for the web app."
  default     = "warnwatcher.com"
}

variable "www_subdomain" {
  type        = string
  description = "www host label."
  default     = "www"
}

variable "api_subdomain" {
  type        = string
  description = "API host label."
  default     = "api"
}

variable "enable_custom_domains" {
  type        = bool
  description = "Enable custom domain bindings on CloudFront and API Gateway after ACM certificates are validated."
  default     = false
}
