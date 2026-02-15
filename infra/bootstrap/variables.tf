variable "project_name" {
  type        = string
  description = "Project name prefix for backend resources."
  default     = "WARNwatcher"
}

variable "region" {
  type        = string
  description = "AWS region for backend resources."
  default     = "us-west-2"
}
