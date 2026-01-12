import json
import os
import requests
import xml.etree.ElementTree as ET

# Environment variables
BACKEND_URL = os.environ.get('BACKEND_URL', 'https://backend.example.com/soap/UnderwritingService')

# --- XML/SOAP Helper Functions ---

SOAP_ENV_NS = 'http://schemas.xmlsoap.org/soap/envelope/'
WSSE_NS = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd'
WSU_NS = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd'

ET.register_namespace('soap', SOAP_ENV_NS)
ET.register_namespace('wsse', WSSE_NS)
ET.register_namespace('wsu', WSU_NS)

def build_wsse_header(username, password):
    """Builds the WS-Security UsernameToken header safely using ElementTree."""
    security_header = ET.Element(f'{{{WSSE_NS}}}Security')
    token = ET.SubElement(security_header, f'{{{WSSE_NS}}}UsernameToken', {f'{{{WSU_NS}}}Id': 'UsernameToken-1'})
    user_el = ET.SubElement(token, f'{{{WSSE_NS}}}Username')
    user_el.text = username
    pass_el = ET.SubElement(token, f'{{{WSSE_NS}}}Password', {'Type': 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText'})
    pass_el.text = password
    return security_header

def create_soap_envelope(body_content, wsse_header=None):
    """Creates a complete SOAP envelope."""
    envelope = ET.Element(f'{{{SOAP_ENV_NS}}}Envelope')
    header = ET.SubElement(envelope, f'{{{SOAP_ENV_NS}}}Header')
    if wsse_header is not None:
        header.append(wsse_header)
    body = ET.SubElement(envelope, f'{{{SOAP_ENV_NS}}}Body')
    body.append(body_content)
    return ET.tostring(envelope, encoding='unicode')

def json_to_xml_elements(parent_element, json_data):
    """Recursively converts a dictionary to XML elements."""
    if isinstance(json_data, dict):
        for key, value in json_data.items():
            child = ET.SubElement(parent_element, key)
            json_to_xml_elements(child, value)
    elif isinstance(json_data, list):
        for item in json_data:
            # Assuming list contains dicts, might need more complex logic
            json_to_xml_elements(parent_element, item)
    else:
        parent_element.text = str(json_data)

# --- Main Handler ---

def handler(event, context):
    """Handles the API Gateway request, transforms JSON to SOAP, and calls the backend."""
    print(f"Received event: {json.dumps(event)}")

    try:
        # 1. Get identity from authorizer context
        auth_context = event.get('requestContext', {}).get('authorizer', {})
        username = auth_context.get('username')
        password = auth_context.get('password')
        if not username or not password:
            return {'statusCode': 403, 'body': 'Forbidden: No identity context found.'}

        # 2. Get incoming JSON body and path
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return {'statusCode': 400, 'body': 'Invalid JSON in request body.'}
        
        path = event.get('path', '')

        # 3. Determine SOAP operation based on path (replicating XSLT logic)
        if path == '/v1/customer':
            operation_name = 'SaveCustomerInfo'
            # Wrapper elements per XSLT
            soap_body_content = ET.Element(operation_name)
            json_to_xml_elements(ET.SubElement(soap_body_content, 'Customer'), body.get('customer'))
            json_to_xml_elements(ET.SubElement(soap_body_content, 'Address'), body.get('address'))
            json_to_xml_elements(ET.SubElement(soap_body_content, 'Demographics'), body.get('demographics'))
            json_to_xml_elements(ET.SubElement(soap_body_content, 'Employment'), body.get('employment'))
        elif path == '/v1/underwriting/submit':
            operation_name = 'SubmitApplication'
            # Wrapper elements per XSLT
            soap_body_content = ET.Element(operation_name)
            json_to_xml_elements(ET.SubElement(soap_body_content, 'Applicant'), body.get('customer'))
            json_to_xml_elements(ET.SubElement(soap_body_content, 'Address'), body.get('address'))
            json_to_xml_elements(ET.SubElement(soap_body_content, 'Demographics'), body.get('demographics'))
            json_to_xml_elements(ET.SubElement(soap_body_content, 'Employment'), body.get('employment'))
        else:
            return {'statusCode': 404, 'body': f'Endpoint {path} not found.'}

        # 4. Build WS-Security header
        wsse_header = build_wsse_header(username, password)

        # 5. Construct the full SOAP envelope
        soap_request = create_soap_envelope(soap_body_content, wsse_header)
        print(f"Constructed SOAP Request: {soap_request}")

        # 6. Call the backend SOAP service
        headers = {'Content-Type': 'text/xml; charset=utf-8'}
        
        response = requests.post(BACKEND_URL, data=soap_request.encode('utf-8'), headers=headers, timeout=10)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # 7. Return backend response to the caller
        return {
            'statusCode': response.status_code,
            'headers': {'Content-Type': 'application/xml'},
            'body': response.text
        }

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Backend request failed: {e}")
        return {'statusCode': 502, 'body': f'Bad Gateway: Could not connect to backend service. {e}'}
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")
        return {'statusCode': 500, 'body': f'Internal Server Error: {e}'}
