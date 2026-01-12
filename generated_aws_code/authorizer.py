import base64
import json
import os
import boto3
from ldap3 import Server, Connection, ALL, Tls
import ssl

# Environment variables
LDAP_SECRET_ARN = os.environ.get('LDAP_SECRET_ARN')
AUTH_GROUP_DN = os.environ.get('AUTH_GROUP_DN') # e.g., 'CN=Underwriters,OU=Groups,DC=example,DC=com'

# Boto3 client
session = boto3.session.Session()
secrets_client = session.client(service_name='secretsmanager')

# Cached secret
ldap_secret = None

def get_ldap_secret():
    """Fetches LDAP credentials from AWS Secrets Manager."""
    global ldap_secret
    if ldap_secret:
        return ldap_secret
    
    try:
        get_secret_value_response = secrets_client.get_secret_value(SecretId=LDAP_SECRET_ARN)
        ldap_secret = json.loads(get_secret_value_response['SecretString'])
        return ldap_secret
    except Exception as e:
        print(f"ERROR: Could not retrieve LDAP secret: {e}")
        raise e

def handler(event, context):
    """Handles API Gateway authorizer request."""
    print(f"Received event: {json.dumps(event)}")
    
    try:
        secret = get_ldap_secret()
        ldap_host = secret['host']
        ldap_port = int(secret.get('port', 389))
        base_dn = secret['base_dn']
        use_ssl = str(secret.get('use_ssl', 'false')).lower() == 'true'

        auth_header = event.get('headers', {}).get('Authorization')
        if not auth_header or not auth_header.lower().startswith('basic '):
            print("ERROR: Missing or invalid Authorization header")
            return generate_policy('user', 'Deny', event['methodArn'])

        encoded_creds = auth_header.split(' ')[1]
        decoded_creds = base64.b64decode(encoded_creds).decode('utf-8')
        username, password = decoded_creds.split(':', 1)

        # Find the user's DN
        bind_dn = secret['bind_dn']
        bind_password = secret['bind_password']
        
        server_options = {'host': ldap_host, 'port': ldap_port, 'get_info': ALL}
        if use_ssl:
            server_options['use_ssl'] = True
            tls_config = Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLSv1_2)
            server_options['tls'] = tls_config
            
        server = Server(**server_options)

        with Connection(server, user=bind_dn, password=bind_password, auto_bind=True) as conn:
            search_filter = f'(|(uid={username})(sAMAccountName={username}))' 
            conn.search(search_base=base_dn, search_filter=search_filter, attributes=['*'])
            
            if not conn.entries:
                print(f"Authentication failed: User '{username}' not found.")
                return generate_deny_policy(event['methodArn'])
            
            user_dn = conn.entries[0].entry_dn

        # Authenticate as the user
        with Connection(server, user=user_dn, password=password, auto_bind=True) as user_conn:
            print(f"Authentication successful for user DN: {user_dn}")
            # Authorize: Check group membership
            # The search for group membership should be done with the bind user conexão, not the end user.
            with Connection(server, user=bind_dn, password=bind_password, auto_bind=True) as admin_conn:
                # This filter checks if the user is a direct or nested member of the group
                is_member = admin_conn.search(AUTH_GROUP_DN, f'(member:1.2.840.113556.1.4.1941:={user_dn})', attributes=['cn'])
                if not is_member or not admin_conn.entries:
                    print(f"Authorization failed: User '{username}' is not in group '{AUTH_GROUP_DN}'.")
                    return generate_deny_policy(event['methodArn'])

        print(f"Authorization successful for user '{username}'.")
        # Pass username and password to backend lambda for WS-Security
        authorizer_context = {
            "username": username,
            "password": password
        }
        return generate_allow_policy(username, event['methodArn'], authorizer_context)

    except Exception as e:
        print(f"ERROR: An exception occurred in the authorizer: {e}")
        return generate_deny_policy(event['methodArn'])

def generate_policy(principal_id, effect, resource, context=None):
    policy = {
        'principalId': principal_id,
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Action': 'execute-api:Invoke',
                    'Effect': effect,
                    'Resource': resource
                }
            ]
        }
    }
    if context:
        policy['context'] = context
    return policy

def generate_allow_policy(principal_id, resource, context):
    return generate_policy(principal_id, 'Allow', resource, context)

def generate_deny_policy(resource):
    return generate_policy('user', 'Deny', resource)
