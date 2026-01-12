import base64
import json
import os
import boto3
from ldap3 import Server, Connection, ALL, NTLM, Tls
import ssl

# --- Environment Variables ---
LDAP_SERVER = os.environ.get('LDAP_SERVER')
LDAP_PORT = int(os.environ.get('LDAP_PORT', 389))
LDAP_BASE_DN = os.environ.get('LDAP_BASE_DN')
LDAP_AUTH_GROUP = os.environ.get('LDAP_AUTH_GROUP')
LDAP_CRED_SECRET_ARN = os.environ.get('LDAP_CRED_SECRET_ARN')

# Globals for connection pooling
secrets_client = boto3.client('secretsmanager')
ldap_bind_creds = None

def get_ldap_bind_credentials():
    """Retrieve LDAP bind credentials from Secrets Manager."""
    global ldap_bind_creds
    if ldap_bind_creds:
        return ldap_bind_creds

    try:
        response = secrets_client.get_secret_value(SecretId=LDAP_CRED_SECRET_ARN)
        secret = json.loads(response['SecretString'])
        ldap_bind_creds = secret
        return ldap_bind_creds
    except Exception as e:
        print(f"ERROR: Could not retrieve LDAP bind secret: {e}")
        raise

def handler(event, context):
    """Lambda authorizer to perform LDAP authentication and authorization."""
    print(f"Event: {event}")

    try:
        auth_header = event.get('headers', {}).get('authorization', '')
        if not auth_header.lower().startswith('basic '):
            print("Authorization header is not Basic type")
            return generate_policy('user', 'Deny', event['methodArn'])

        encoded_creds = auth_header.split(' ')[1]
        decoded_creds = base64.b64decode(encoded_creds).decode('utf-8')
        username, password = decoded_creds.split(':', 1)

        # --- 1. Authenticate user via LDAP bind ---
        # In a production environment, use LDAPS (port 636) and properly configure TLS
        # tls_config = Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLSv1_2, ca_certs_file='/path/to/ca.pem')
        server = Server(LDAP_SERVER, port=LDAP_PORT, get_info=ALL)
        
        # Use user's credentials to attempt a bind
        # Assuming user DN can be constructed like this. Adjust if needed.
        user_dn = f"cn={username},ou=Users,{LDAP_BASE_DN}" 

        print(f"Attempting to bind with user DN: {user_dn}")
        with Connection(server, user=user_dn, password=password) as conn:
            if not conn.bind():
                print(f"Authentication failed for user: {username}. Reason: {conn.result}")
                # Explicitly deny on auth failure
                return generate_policy(username, 'Deny', event['methodArn'])
            print(f"Authentication successful for user: {username}")

            # --- 2. Authorize user based on group membership ---
            # Re-bind with service account to perform search if necessary
            # bind_creds = get_ldap_bind_credentials()
            # conn.rebind(user=bind_creds['username'], password=bind_creds['password'])
            
            # Search for the user's membership in the authorized group
            # The filter checks if the authorized group has the user as a member.
            # This might need adjustment based on schema (e.g., 'member' vs 'uniqueMember')
            search_filter = f"(&(objectClass=groupOfNames)(cn={LDAP_AUTH_GROUP.split(',')[0].split('=')[1]})(member={user_dn}))"
            is_authorized = conn.search(LDAP_AUTH_GROUP, search_filter, attributes=['cn'])
            
            if not is_authorized or len(conn.entries) == 0:
                print(f"Authorization failed: User '{username}' is not in group '{LDAP_AUTH_GROUP}'")
                return generate_policy(username, 'Deny', event['methodArn'])
            
            print(f"Authorization successful: User '{username}' is in group '{LDAP_AUTH_GROUP}'")

        # --- 3. Generate Allow policy and pass context to integration --- 
        policy = generate_policy(username, 'Allow', event['methodArn'])
        # Pass username and password to the backend lambda for WS-Security
        policy['context'] = {
            'username': username,
            'password': password
        }
        return policy

    except Exception as e:
        print(f"An unexpected error occurred in the authorizer: {e}")
        # Deny access in case of any errors
        return generate_policy('user', 'Deny', event['methodArn'])

def generate_policy(principal_id, effect, resource):
    """Helper function to create an IAM policy document."""
    return {
        'principalId': principal_id,
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [{
                'Action': 'execute-api:Invoke',
                'Effect': effect,
                'Resource': resource
            }]
        }
    }
