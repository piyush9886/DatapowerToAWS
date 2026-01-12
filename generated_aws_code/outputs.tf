output "api_gateway_invoke_url" {
  description = "The invoke URL for the deployed API Gateway stage."
  value       = aws_api_gateway_stage.api_stage.invoke_url
}

output "ldap_credentials_secret_arn" {
  description = "The ARN of the Secrets Manager secret holding LDAP credentials."
  value       = aws_secretsmanager_secret.ldap_creds.arn
}
