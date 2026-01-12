provider "aws" {
  region = var.aws_region
}

locals {
  project_name = "underwriting-api"
}

# --- Secrets Manager for LDAP Credentials ---
resource "aws_secretsmanager_secret" "ldap_bind_credentials" {
  name        = "${local.project_name}/ldap-bind-credentials"
  description = "Credentials for the LDAP bind user."
}

resource "aws_secretsmanager_secret_version" "ldap_bind_credentials_version" {
  secret_id = aws_secretsmanager_secret.ldap_bind_credentials.id
  secret_string = jsonencode({
    username = var.ldap_bind_dn
    password = var.ldap_bind_password
  })
}

# --- Lambda Layers for Dependencies ---
data "archive_file" "lambda_layer_packages" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/layer"
  output_path = "${path.module}/lambda_layer.zip"
}

resource "aws_lambda_layer_version" "python_deps_layer" {
  layer_name        = "${local.project_name}-python-deps"
  description       = "Python dependencies for ldap3 and requests"
  filename          = data.archive_file.lambda_layer_packages.output_path
  source_code_hash  = data.archive_file.lambda_layer_packages.output_base64sha256
  compatible_runtimes = ["python3.9"]
}

# --- IAM Roles and Policies ---
resource "aws_iam_role" "lambda_authorizer_role" {
  name               = "${local.project_name}-authorizer-role"
  assume_role_policy = file("${path.module}/../iam/lambda_authorizer_role.json")
}

resource "aws_iam_policy" "lambda_authorizer_policy" {
  name   = "${local.project_name}-authorizer-policy"
  policy = templatefile("${path.module}/../iam/lambda_authorizer_policy.json", {
    aws_region = var.aws_region,
    aws_account_id = data.aws_caller_identity.current.account_id,
    secret_arn = aws_secretsmanager_secret.ldap_bind_credentials.arn
  })
}

resource "aws_iam_role_policy_attachment" "authorizer_policy_attach" {
  role       = aws_iam_role.lambda_authorizer_role.name
  policy_arn = aws_iam_policy.lambda_authorizer_policy.arn
}

resource "aws_iam_role" "lambda_transformer_role" {
  name               = "${local.project_name}-transformer-role"
  assume_role_policy = file("${path.module}/../iam/lambda_transformer_role.json")
}

resource "aws_iam_policy" "lambda_transformer_policy" {
  name   = "${local.project_name}-transformer-policy"
  policy = templatefile("${path.module}/../iam/lambda_transformer_policy.json", {
    aws_region = var.aws_region,
    aws_account_id = data.aws_caller_identity.current.account_id
  })
}

resource "aws_iam_role_policy_attachment" "transformer_policy_attach" {
  role       = aws_iam_role.lambda_transformer_role.name
  policy_arn = aws_iam_policy.lambda_transformer_policy.arn
}

# --- Lambda Functions ---
data "archive_file" "authorizer_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambda/authorizer.py"
  output_path = "${path.module}/authorizer.zip"
}

resource "aws_lambda_function" "authorizer_lambda" {
  function_name = "${local.project_name}-authorizer"
  role          = aws_iam_role.lambda_authorizer_role.arn
  handler       = "authorizer.handler"
  runtime       = "python3.9"
  filename      = data.archive_file.authorizer_lambda_zip.output_path
  source_code_hash = data.archive_file.authorizer_lambda_zip.output_base64sha256
  timeout       = 10

  layers = [aws_lambda_layer_version.python_deps_layer.arn]

  environment {
    variables = {
      LDAP_SERVER       = var.ldap_server_host
      LDAP_PORT         = var.ldap_server_port
      LDAP_BASE_DN      = var.ldap_base_dn
      LDAP_AUTH_GROUP   = var.ldap_auth_group
      LDAP_CRED_SECRET_ARN = aws_secretsmanager_secret.ldap_bind_credentials.arn
    }
  }
}

data "archive_file" "transformer_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambda/transformer.py"
  output_path = "${path.module}/transformer.zip"
}

resource "aws_lambda_function" "transformer_lambda" {
  function_name = "${local.project_name}-transformer"
  role          = aws_iam_role.lambda_transformer_role.arn
  handler       = "transformer.handler"
  runtime       = "python3.9"
  filename      = data.archive_file.transformer_lambda_zip.output_path
  source_code_hash = data.archive_file.transformer_lambda_zip.output_base64sha256
  timeout       = 30

  layers = [aws_lambda_layer_version.python_deps_layer.arn]

  environment {
    variables = {
      BACKEND_URL = var.backend_soap_url
    }
  }
}

# --- API Gateway ---
resource "aws_cloudwatch_log_group" "api_gateway_logs" {
  name              = "/aws/api-gateway/${local.project_name}"
  retention_in_days = 30
}

resource "aws_api_gateway_rest_api" "underwriting_api" {
  name        = local.project_name
  description = "Underwriting API migrated from DataPower"
  body = templatefile("${path.module}/../openapi.yaml", {
    aws_region = var.aws_region,
    authorizer_lambda_arn = aws_lambda_function.authorizer_lambda.invoke_arn,
    transformer_lambda_arn = aws_lambda_function.transformer_lambda.invoke_arn
  })

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_deployment" "api_deployment" {
  rest_api_id = aws_api_gateway_rest_api.underwriting_api.id

  triggers = {
    redeployment = sha1(jsonencode(aws_api_gateway_rest_api.underwriting_api.body))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "api_stage" {
  stage_name    = "v1"
  rest_api_id   = aws_api_gateway_rest_api.underwriting_api.id
  deployment_id = aws_api_gateway_deployment.api_deployment.id

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway_logs.arn
    format          = jsonencode({
      requestId               = "$context.requestId"
      ip                      = "$context.identity.sourceIp"
      caller                  = "$context.identity.caller"
      user                    = "$context.identity.user"
      requestTime             = "$context.requestTime"
      httpMethod              = "$context.httpMethod"
      resourcePath            = "$context.resourcePath"
      status                  = "$context.status"
      protocol                = "$context.protocol"
      responseLength          = "$context.responseLength"
    })
  }

  variables = {
    lambdaVersion = "latest"
  }
}

# --- CloudFront for URL Rewrite ---
resource "aws_s3_bucket" "cloudfront_logs" {
  bucket = "${local.project_name}-cloudfront-logs-${data.aws_caller_identity.current.account_id}"
}

resource "aws_iam_role" "lambda_edge_role" {
  name = "${local.project_name}-lambda-edge-role"
  assume_role_policy = file("${path.module}/../iam/lambda_edge_role.json")
}

resource "aws_iam_policy" "lambda_edge_policy" {
  name   = "${local.project_name}-lambda-edge-policy"
  policy = templatefile("${path.module}/../iam/lambda_edge_policy.json", {
    aws_region = var.aws_region,
    aws_account_id = data.aws_caller_identity.current.account_id
  })
}

resource "aws_iam_role_policy_attachment" "edge_policy_attach" {
  role       = aws_iam_role.lambda_edge_role.name
  policy_arn = aws_iam_policy.lambda_edge_policy.arn
}

data "archive_file" "rewrite_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambda/rewrite_handler.py"
  output_path = "${path.module}/rewrite_handler.zip"
}

resource "aws_lambda_function" "rewrite_handler_lambda_edge" {
  provider      = aws.us-east-1 # Lambda@Edge functions must be in us-east-1
  function_name = "${local.project_name}-rewrite-handler"
  role          = aws_iam_role.lambda_edge_role.arn
  handler       = "rewrite_handler.handler"
  runtime       = "python3.9"
  filename      = data.archive_file.rewrite_lambda_zip.output_path
  source_code_hash = data.archive_file.rewrite_lambda_zip.output_base64sha256
  publish       = true # Required for Lambda@Edge
}

resource "aws_cloudfront_distribution" "rewrite_distribution" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "Distribution for URL Rewrite to SOAP backend"

  origin {
    domain_name = trimsuffix(split("://", var.backend_soap_url)[1], "/soap/UnderwritingService")
    origin_id   = "backend-soap-service"

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "https-only"
      origin_ssl_protocols     = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    allowed_methods  = ["POST", "OPTIONS"]
    cached_methods   = ["OPTIONS"]
    target_origin_id = "backend-soap-service"
    viewer_protocol_policy = "redirect-to-https"
    forwarded_values {
      query_string = false
      headers      = ["Authorization", "Content-Type"]
      cookies {
        forward = "none"
      }
    }
    
    lambda_function_association {
      event_type   = "origin-request"
      lambda_arn   = aws_lambda_function.rewrite_handler_lambda_edge.qualified_arn
      include_body = false
    }
  }

  logging_config {
    include_cookies = false
    bucket          = aws_s3_bucket.cloudfront_logs.bucket_domain_name
    prefix          = "rewrites/"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

data "aws_caller_identity" "current" {}
