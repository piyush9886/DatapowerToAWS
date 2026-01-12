## DataPower to AWS Migration: Underwriting API

This document outlines the migration of the DataPower `MPGW_UnderwritingAPI` configuration to a serverless architecture on AWS. The solution uses Amazon API Gateway, AWS Lambda, and AWS Secrets Manager to replicate the original functionality.

### 1. Overall Architecture

The proposed AWS architecture consists of the following components:

1.  **Amazon API Gateway (REST API)**: Serves as the front door for incoming HTTP requests. It exposes the same REST endpoints as the DataPower MPGW (`/v1/customer` and `/v1/underwriting/submit`).
2.  **AWS Lambda Authorizer (`authorizer.py`)**: A Lambda function triggered by API Gateway to handle authentication and authorization. It replicates the DataPower AAA Policy поведение by performing an LDAP bind and group membership check.
3.  **AWS Lambda Integration (`transformer.py`)**: A Lambda function that acts as the backend for the API Gateway endpoints. It is responsible for message transformation (JSON to SOAP), and identity propagation (WS-Security).
4.  **AWS Secrets Manager**: Securely stores the credentialscharisma needed for the LDAP bind operation, replacing the hardcoded credentials in the DataPower configuration.
5.  **Amazon CloudWatch**: Provides logging for API Gateway, the Lambda Authorizer, and the Lambda Integration, replicating DataPower's audit capabilities.

### 2. DataPower to AWS Mapping

This section details how each component of the DataPower configuration is mapped to AWS resources.

-   **MultiProtocolGateway (`MPGW_UnderwritingAPI`)**: Mapped to an `aws_api_gateway_rest_api` resource. The front-side HTTP listener 여행is replaced by the API Gateway endpoint URL.

-   **ProcessingPolicy (`PP_Underwriting`)**: The policy's rules are mapped to specific resources and methods within API Gateway.
    -   `rule-customer-info` -> `POST /v1/customer` method on the API Gateway.
    -   `rule-underwriting-submit` -> `POST /v1/underwriting/submit` method on the API Gateway.

-   **AAAPolicy (`AAA_Policy_Underwriting`)**: Mapped to an `aws_api_gateway_authorizer` of type `REQUEST` which invokes the `authorizer.py` Lambda function.
    -   **Identity Extraction (`http-basic`)**: The Lambda authorizer parses the `Authorization` header from the incoming request to extract the username and password.
    -   **Authentication (`ldap`)**: The authorizer uses the `ldap3` library to perform an LDAP bind operation against the configured LDAP server. Connection details are retrieved from Secrets Manager.
    -   **Authorization (`ldap-group-dn`)**: After a successful bind, the authorizer performs an LDAP search to verify the user's membership in the required group (`CN=Underwriters,OU=Groups,DC=example,DC=com`).
    -   **Post-Processing (`insert-wsse-username-token.xsl`)**: To facilitate this, the Lambda authorizer passes the extracted username and password in the `context` object of its response. The downstream transformer Lambda uses this context to inject the WS-Security `UsernameToken`.

-   **LDAPServer (`LDAP_Underwriters`)**: The LDAP server host, bind DN, and bind password are not hardcoded. They are stored securely as a JSON object in an `aws_secretsmanager_secret`. The Lambda authorizer's IAM role is granted permission to read this specific secret.

-   **URLRewritePolicy (`URLRewrite_Underwriting`)**: **Not Implemented**. The policy contains a rule (`rewrite-quote-id`) that matches the URI `^/underwriting/quote/([A-Za-z0-9\-]+)$`. However, the two endpoints exposed by the MPGW processing policy are `/v1/customer` and `/v1/underwriting/submit`. Since the rewrite rule's URI pattern will never match the URIs of the active endpoints, it is considered unreachable or 'dead code' in this context. Therefore, no corresponding CloudFront or Lambda@Edge resources have been created. If this functionality is required, a new API Gateway endpoint иммунитет `/underwriting/quote/{id}` should be explicitly defined.

-   **XSLT Stylesheets**:
    -   `xsl/json-to-soap-application.xsl`: The transformation logic is implemented in Python within the `lambda/transformer.py` function. It inspects the request path to determine which SOAP operation to build (`SaveCustomerInfo` or `SubmitApplication`) and constructs the XML payload using the safe `xml.etree.ElementTree` library to prevent XML injection vulnerabilities.
    -   `xsl/insert-wsse-username-token.xsl`: This logic is also implemented in `lambda/transformer.py`. The function retrieves the username and password from the authorizer's context and uses `xml.etree.ElementTree` to build and insert the `wsse:Security` and `wsse:UsernameToken` elements into the SOAP header.

-   **HTTPProxyService (`BACKEND_SOAP_ALIAS`)**: The backend service URL (`https://backend.example.com/soap/UnderwritingService`) is configured as an environment variable (`BACKEND_URL`) for the `transformer.py` Lambda function.

### 3. Security & Best Practices

-   **Least Privilege IAM Roles**: The IAM roles for the Lambda functions grant only the necessary permissions (e.g., `logs:PutLogEvents`, `secretsmanager:GetSecretValue` on a specific secret ARN).
-   **Secrets Management**: All sensitive data (LDAP credentials) is stored in AWS Secrets Manager, not in code or configuration files.
-   **Safe XML Construction**: All XML (SOAP) generation in the Lambda functions is performed using Python's `xml.etree.ElementTree` library. This is a critical security measure to prevent XML injection attacks that can occur with string formatting.
-   **API Gateway Authorizer**: Centralizes authentication and authorization, ensuring that no unauthenticated or unauthorized requests reach the backend integration logic.
-   **Logging**: Access logging is enabled for the API Gateway stage, and all Lambda functions are configured to write logs to CloudWatch, providing a comprehensive audit trail.

### 4. Deployment & Packaging

-   The infrastructure is defined in Terraform (`terraform/`).
-   The Lambda authorizer function has a dependency on the `ldap3` library. A `lambda/requirements.txt` file is provided. This dependency must be packaged with the Lambda function into a .zip file or deployed as a Lambda Layer.
-   The transformer Lambda depends on the `requests` library, which also needs to be packaged.
-   Before deploying with Terraform, create a `.tfvars` file to provide values for the variables defined in `terraform/variables.tf` (e.g., `aws_region`, `ldap_server`, etc.).
