provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  project_name = var.project_name
  tags = {
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

# --- Secrets Manager for LDAP Credentials ---
resource "aws_secretsmanager_secret" "ldap_creds" {
  name = "${local.project_name}-ldap-creds"
  description = "Credentials for LDAP server access"
  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "ldap_creds_v1" {
  secret_id = aws_secretsmanager_secret.ldap_creds.id
  secret_string = jsonencode({
    host          = var.ldap_server_host
    port          = var.ldap_server_port
    base_dn       = var.ldap_base_dn
    bind_dn       = var.ldap_bind_dn
    bind_password = var.ldap_bind_password
    use_ssl       = var.ldap_use_ssl
  })
}

# --- IAM Roles and Policies ---

# IAM for Lambda Authorizer
resource "aws_iam_role" "lambda_authorizer_role" {
  name = "${local.project_name}-authorizer-lambda-role"
  assume_role_policy = file("${path.module}/../iam/lambda_authorizer_role.json")
  tags = local.tags
}

resource "aws_iam_policy" "lambda_authorizer_policy" {
  name = "${local.project_name}-authorizer-lambda-policy"
  policy = templatefile("${path.module}/../iam/lambda_authorizer_policy.json", {
    region        = data.aws_region.current.name
    account_id    = data.aws_caller_identity.current.account_id
    project_name  = local.project_name
    ldap_secret_arn = aws_secretsmanager_secret.ldap_creds.arn
  })
}

resource "aws_iam_role_policy_attachment" "authorizer_policy_attach" {
  role       = aws_iam_role.lambda_authorizer_role.name
  policy_arn = aws_iam_policy.lambda_authorizer_policy.arn
}

# IAM for Lambda Transformer
resource "aws_iam_role" "lambda_transformer_role" {
  name = "${local.project_name}-transformer-lambda-role"
  assume_role_policy = file("${path.module}/../iam/lambda_transformer_role.json")
  tags = local.tags
}

resource "aws_iam_policy" "lambda_transformer_policy" {
  name = "${local.project_name}-transformer-lambda-policy"
  policy = templatefile("${path.module}/../iam/lambda_transformer_policy.json", {
    region       = data.aws_region.current.name
    account_id   = data.aws_caller_identity.current.account_id
    project_name = local.project_name
  })
}

resource "aws_iam_role_policy_attachment" "transformer_policy_attach" {
  role       = aws_iam_role.lambda_transformer_role.name
  policy_arn = aws_iam_policy.lambda_transformer_policy.arn
}

# --- Lambda Functions ---

data "archive_file" "lambda_authorizer_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.build}/authorizer.zip"
  # Note: In a real project, you would build a zip with dependencies (ldap3) here.
}

data "archive_file" "lambda_transformer_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.build}/transformer.zip"
  # Note: In a real project, you would build a zip with dependencies (requests) here.
}

resource "aws_lambda_function" "authorizer" {
  function_name = "${local.project_name}-authorizer"
  role          = aws_iam_role.lambda_authorizer_role.arn
  handler       = "authorizer.handler"
  runtime       = "python3.9"
  timeout       = 30
  #filename      = data.archive_file.lambda_authorizer_zip.output_path # Use a pre-built zip with dependencies
  #source_code_hash = data.archive_file.lambda_authorizer_zip.output_base64sha256
  filename      = "${path.module}/../lambda/authorizer.py" # Placeholder, replace with zip

  environment {
    variables = {
      LDAP_SECRET_ARN = aws_secretsmanager_secret.ldap_creds.arn
      AUTH_GROUP_DN   = var.ldap_auth_group_dn
    }
  }
  tags = local.tags
}

resource "aws_lambda_function" "transformer" {
  function_name = "${local.project_name}-transformer"
  role          = aws_iam_role.lambda_transformer_role.arn
  handler       = "transformer.handler"
  runtime       = "python3.9"
  timeout       = 30
  #filename      = data.archive_file.lambda_transformer_zip.output_path # Use a pre-built zip with dependencies
  #source_code_hash = data.archive_file.lambda_transformer_zip.output_base64sha256
  filename      = "${pathModule}/../lambda/transformer.py" # Placeholder, replace with zip

  environment {
    variables = {
      BACKEND_URL = var.backend_soap_url
    }
  }
  tags = local.tags
}

# --- API Gateway ---

resource "aws_api_gateway_rest_api" "api" {
  name        = "${local.project_name}-api"
  description = "Migrated Underwriting API from DataPower"
  body        = templatefile("${path.module}/../openapi.yaml", {
    region                 = data.aws_region.current.name
    lambda_authorizer_arn  = aws_lambda_function.authorizer.invoke_arn
    lambda_transformer_arn = aws_lambda_function.transformer.invoke_arn
  })
  endpoint_configuration {
    types = ["REGIONAL"]
  }
  tags = local.tags
}

resource "aws_cloudwatch_log_group" "api_gateway_logs" {
  name              = "API-Gateway-Execution-Logs_${aws_api_gateway_rest_api.api.id}/v1"
  retention_in_days = 30
  tags = local.tags
}

resource "aws_api_gateway_deployment" "api_deployment" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = sha1(jsonencode(aws_api_gateway_rest_api.api.body))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "api_stage" {
  deployment_id = aws_api_gateway_deployment.api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.api.id
  stage_name    = "v1"

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
      authorizerPrincipalId = "$context.authorizer.principalId"
    })
  }

  variables = {
    deployed_at = timestamp()
  }

  tags = local.tags
}

resource "aws_lambda_permission" "allow_api_gateway_authorizer" {
  statement_id  = "AllowAPIGatewayInvokeAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

resource "aws_lambda_permission" "allow_api_gateway_transformer" {
  statement_id  = "AllowAPIGatewayInvokeTransformer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.transformer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}
