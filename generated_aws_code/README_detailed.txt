## DataPower to AWS Migration: Detailed Mapping

This document outlines the mapping of the provided DataPower configuration (`export.xml`) to the generated AWS resources. The goal is to replicate the original functionality using a serverless architecture on AWS, prioritizing security, scalability, and maintainability.

### 1. High-Level Architecture

The DataPower `MultiProtocolGateway` is migrated to a combination of Amazon API Gateway, AWS Lambda, and Amazon CloudFront.

- **API Gateway**: Serves as the primary entry point for the REST API, handling request validation, routing, and authorizaton for the `/v1/customer` and `/v1/underwriting/submit` endpoints.
- **AWS Lambda**: Provides the business logic:
    - A **Lambda Authorizer** replicates the DataPower AAA policy (LDAP authentication and authorization).
    - An **Integration Lambda** replicates the XSLT transformations (JSON to SOAP) and backend routing.
    - A **Lambda@Edge** function attached to a CloudFront distribution replicates the URL Rewrite policy for a separate path.
- **Amazon CloudFront**: A distribution is used to handle the `URLRewritePolicy` which matches a path not defined in the main API Gateway REST API. This allows for header injection (`SOAPAction`) at the edge.
- **AWS Secrets Manager**: Securely stores credentials for the LDAP bind user, which are accessed by the Lambda Authorizer.
- **IAM**: Provides least-privilege roles and policies for all AWS resources.
- **CloudWatch**: Centralizes logging for API Gateway, Lambda, and CloudFront.

---

### 2. Component-by-Component Mapping

#### 2.1. `MPGW_UnderwritingAPI` (Multi-Protocol Gateway)

- **DataPower Element**: `dp:MultiProtocolGateway` named `MPGW_UnderwritingAPI`.
- **AWS Mapping**: `aws_api_gateway_rest_api` (`underwriting_api`).
- **Details**:
    - The front-side HTTP listener on port `8080` is replaced by the API Gateway endpoint.
    - The `parse-mode=json` behavior is implicitly handled by API Gateway, which passes the JSON payload to the integration Lambda.
    - The `processing-policy` is implemented by the combination of the Lambda Authorizer and the Integration Lambda.

#### 2.2. `PP_Underwriting` (Processing Policy)

- **DataPower Element**: `dp:ProcessingPolicy` named `PP_Underwriting` with its rules.
- **AWS Mapping**: API Gateway method integrations and the Integration Lambda (`lambda/transformer.py`).
- **Details**:
    - **`rule-customer-info`** (`POST /v1/customer`): Mapped to an `aws_api_gateway_method` for `POST` on the `/v1/customer` resource. This method is configured to use the Lambda Authorizer and integrate with the `transformer_lambda`.
    - **`rule-underwriting-submit`** (`POST /v1/underwriting/submit`): Mapped to an `aws_api_gateway_method` for `POST` on the `/v1/underwriting/submit` resource, also using the same authorizer and integration Lambda.
    - The routing logic within the rules (`<dp:Route>`) is now handled inside the `transformer_lambda`, which makes an HTTP request to the backend.

#### 2.3. `AAA_Policy_Underwriting` (AAA Policy)

- **DataPower Element**: `dp:AAAPolicy` named `AAA_Policy_Underwriting`.
- **AWS Mapping**: `aws_api_gateway_authorizer` and a Lambda Authorizer function (`lambda/authorizer.py`).
- **Details**:
    - **Identity Extraction (`http-basic`)**: The Lambda Authorizer receives the `Authorization` header from API Gateway and is responsible for parsing the Base64-encoded credentials.
    - **Authentication (`ldap`)**: The authorizer function contains logic (stubbed out) to perform an LDAP bind against the configured server. It retrieves the LDAP bind credentials from an `aws_secretsmanager_secret` (`ldap_bind_credentials`).
    - **Authorization (`ldap-group-dn`)**: After a successful bind, the authorizer performs an LDAP search to verify the user's membership in the required group (`CN=Underwriters,OU=Groups,DC=example,DC=com`).
    - **Post-Processing (`insert-wsse-username-token.xsl`)**: The identity propagation strategy is changed. The Lambda Authorizer passes the authenticated user's username and password to the integration Lambda via the `authorizer.context` dictionary. The integration Lambda (`transformer.py`) then uses this information to build the WS-Security `UsernameToken`, replicating the XSLT's function. This ensures the credentials are used to sign the backend request but are not stored long-term.

#### 2.4. `URLRewrite_Underwriting` (URL Rewrite Policy)

- **DataPower Element**: `dp:URLRewritePolicy` named `URLRewrite_Underwriting`.
- **AWS Mapping**: `aws_cloudfront_distribution` and a Lambda@Edge function (`lambda/rewrite_handler.py`).
- **Details**:
    - The rule `rewrite-quote-id` matches `POST /underwriting/quote/{id}` and injects a `SOAPAction` header. Since this path is not part of the core API endpoints (`/v1/*`), it's handled separately to avoid polluting the main API Gateway definition.
    - A CloudFront distribution is created with the backend SOAP service as its origin.
    - A Lambda@Edge function is associated with the `origin-request` event.
    - This function inspects the incoming request URI. If it matches the pattern, it adds the `SOAPAction: "insurance.com"` header before forwarding the request to the origin. This effectively replicates the DataPower rewrite rule at the CDN edge.

#### 2.5. XSLT Transformations

- **DataPower Elements**: `xsl/json-to-soap-application.xsl` and `xsl/insert-wsse-username-token.xsl`.
- **AWS Mapping**: Python logic within the Integration Lambda (`lambda/transformer.py`).
- **Details**:
    - **`json-to-soap-application.xsl`**: The logic is implemented in Python. The Lambda function inspects the request `path` from the API Gateway event to determine whether to build a `<SaveCustomerInfo>` or `<SubmitApplication>` SOAP body. It uses Python's `xml.etree.ElementTree` library to safely construct the XML, preventing XML injection vulnerabilities from user-provided data.
    - **`insert-wsse-username-token.xsl`**: This logic is also moved into `transformer.py`. It constructs the `wsse:Security` header and `wsse:UsernameToken` using the username and password passed from the Lambda Authorizer's context. This maintains the end-to-end identity propagation.

#### 2.6. `LDAP_Underwriters` & Secrets

- **DataPower Element**: `dp:LDAPServer` and hardcoded bind password.
- **AWS Mapping**: `aws_secretsmanager_secret` and variables in `terraform/variables.tf`.
- **Details**:
    - The LDAP server host, port, and base DN are stored as Terraform variables.
    - The sensitive LDAP bind DN and password (`REPLACE_WITH_SECURE_PASSWORD`) are stored in an `aws_secretsmanager_secret` resource named `ldap_bind_credentials`.
    - The Lambda Authorizer's IAM role is granted specific `secretsmanager:GetSecretValue` permission for this secret only, following the principle of least privilege.

### 3. Security, Logging, and Auditing

- **Identity & Access**: IAM roles are created with minimal permissions for each Lambda function and for API Gateway.
- **Logging**: Access logging is enabled for the API Gateway stage, sending structured JSON logs to a dedicated CloudWatch Log Group. The CloudFront distribution is also configured to send access logs to an S3 bucket. All Lambda functions are granted permissions to write logs to CloudWatch.
- **Auditing**: The DataPower `<dp:audit>on</dp:audit>` function is mapped to the combination of API Gateway and CloudFront access logs, providing a detailed audit trail of all requests.
- **XML Safety**: All SOAP XML generation in the Python Lambda code is performed using `xml.etree.ElementTree` to prevent injection attacks, fulfilling a critical security requirement.

### 4. Assumptions & Design Choices

- **VPC**: The Lambda functions and backend connectivity are assumed to be suitable for running outside a VPC. For production, you would likely place the Lambdas within a VPC for private access to the backend and the LDAP server (via Direct Connect or VPN).
- **Dependencies**: The Python Lambdas require external libraries (`ldap3`, `requests`). The Terraform setup includes a `aws_lambda_layer_version` resource to manage these dependencies, which must be packaged and uploaded to S3.
- **Error Handling**: The provided Lambda stubs include basic error handling. Production-grade implementations should include more robust logic for retries, dead-letter queues (DLQs), and mapping backend errors to appropriate HTTP status codes.
- **URL Rewrite Strategy**: CloudFront with Lambda@Edge was chosen for the URL rewrite rule because it cleanly separates this logic from the primary API Gateway REST API, offers high performance, and is well-suited for header manipulation.
