variable "aws_region" {
  description = "The AWS region to deploy resources."
  type        = string
  default     = "us-east-1"
}

variable "backend_soap_url" {
  description = "The full URL of the backend SOAP service."
  type        = string
  default     = "https://backend.example.com/soap/UnderwritingService"
}

variable "ldap_server_host" {
  description = "Hostname or IP address of the LDAP server."
  type        = string
  default     = "ldap.example.com"
}

variable "ldap_server_port" {
  description = "Port for the LDAP server."
  type        = number
  default     = 389
}

variable "ldap_base_dn" {
  description = "Base DN for LDAP searches."
  type        = string
  default     = "DC=example,DC=com"
}

variable "ldap_bind_dn" {
  description = "The DN of the user for binding to LDAP to perform searches."
  type        = string
  sensitive   = true
  default     = "CN=svc-datapower,OU=ServiceAccounts,DC=example,DC=com"
}

variable "ldap_bind_password" {
  description = "Password for the LDAP bind user."
  type        = string
  sensitive   = true
  default     = "REPLACE_WITH_SECURE_PASSWORD"
}

variable "ldap_auth_group" {
  description = "The DN of the LDAP group required for authorization."
  type        = string
  default     = "CN=Underwriters,OU=Groups,DC=example,DC=com"
}
