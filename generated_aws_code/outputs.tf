output "api_gateway_invoke_url" {
  description = "The invoke URL for the API Gateway stage."
  value       = aws_api_gateway_stage.api_stage.invoke_url
}

output "cloudfront_rewrite_domain" {
  description = "The domain name for the CloudFront distribution handling URL rewrites."
  value       = aws_cloudfront_distribution.rewrite_distribution.domain_name
}

output "lambda_layer_instructions" {
  description = "Instructions for creating the Lambda layer zip file."
  value       = "Create a 'lambda/layer/python' directory. Run 'pip install requests ldap3 -t lambda/layer/python'. The Terraform 'archive_file' data source will zip the 'lambda/layer' directory for you."
}
