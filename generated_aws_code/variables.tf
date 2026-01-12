variable "aws_region" {
  description = "AWS region to deploy resources."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "A unique name for the project to prefix resources."
  type        = string
  default     = "underwriting-api"
}

variable "backend_soap_url" {
  description = "The URL of the backend SOAP service."
  type        = string
  default     = "https://backend.example.com/soap/UnderwritingService"
}

variable "ldap_server_host" {
  description = "Hostname of the LDAP server."
  type        = string
  default     = "ldap.example.com"
}

variable "ldap_server_port" {
  description = "Port of the LDAP server."
  type        = number
  default     = 389
}

variable "ldap_base_dn" {
  description = "Base DN for LDAP searches."
  type        = string
  default     = "DC=example,DC=com"
}

variable "ldap_bind_dn" {
  description = "DN for the service account to bind to LDAP."
  type        = string
  default     = "CN=svc-datapower,OU=ServiceAccounts,DC=example,DC=com"
}

variable "ldap_bind_password" {
  description = "Password for the LDAP service account."
  type        = string
  sensitive   = true
  # Provide this value in a .tfvars file or via environment variable TF_VAR_ldap_bind_password
}

variable "ldap_auth_group_dn" {
  description = "The DN of the LDAP group required for authorization."
  type        = string
  default     = "CN=Underwriters,OU=Groups,DC=example,DC=com"
}

variable "ldap_use_ssl" {
  description = "Whether to use SSL/TLS (LDAPS) to connect to the LDAP server."
  type        = bool
  default     = false
}
