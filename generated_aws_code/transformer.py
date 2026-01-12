import json
import os
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Environment variables
BACKEND_URL = os.environ.get('BACKEND_URL')

# --- XML/SOAP Helper Functions ---

def build_soap_envelope(body_content, security_header=None):
    """Constructs a SOAP envelope safely using ElementTree."""
    # Register namespaces to avoid ns0, ns1 prefixes
    ET.register_namespace('soap', "http://schemas.xmlsoap.org/soap/envelope/")
    
    envelope = ET.Element("{http://schemas.xmlsoap.org/soap/envelope/}Envelope")
    header = ET.SubElement(envelope, "{http://schemas.xmlsoap.org/soap/envelope/}Header")
    body = ET.SubElement(envelope, "{http://schemas.xmlsoap.org/soap/envelope/}Body")

    if security_header is not None:
        header.append(security_header)

    body.append(body_content)
    return envelope

def create_wsse_security_header(username, password):
    """Creates a WS-Security UsernameToken header."""
    ET.register_namespace('wsse', "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd")
    ET.register_namespace('wsu', "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd")

    security_elem = ET.Element("{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}Security")
    token_elem = ET.SubElement(security_elem, "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}UsernameToken")
    token_elem.set("{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}Id", "UsernameToken-1")
    
    user_elem = ET.SubElement(token_elem, "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}Username")
    user_elem.text = username
    
    pass_elem = ET.SubElement(token_elem, "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}Password")
    pass_elem.set("Type", "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText")
    pass_elem.text = password
    
    return security_elem

def json_to_xml_elements(parent, data):
    """Recursively converts a dictionary to XML elements."""
    for key, value in data.items():
        if isinstance(value, dict):
            child = ET.SubElement(parent, key)
            json_to_xml_elements(child, value)
        else:
            child = ET.SubElement(parent, key)
            child.text = str(value)

def prettify_xml(elem):
    """Return a pretty-printed XML string for the Element."""
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

# --- Main Handler ---

def handler(event, context):
    """Handles API Gateway request, transforms JSON to SOAP, and calls backend."""
    print(f"Received event: {json.dumps(event)}")

    try:
        # 1. Get data from event
        body = json.loads(event.get('body', '{}'))
        path = event.get('path', '')
        authorizer_context = event.get('requestContext', {}).get('authorizer', {})
        username = authorizer_context.get('username')
        password = authorizer_context.get('password')

        if not all([username, password]):
            return {'statusCode': 403, 'body': 'Forbidden: Missing authentication context.'}

        # 2. Determine SOAP operation based on path (replicating XSLT logic)
        if path == '/v1/underwriting/submit':
            operation_name = 'SubmitApplication'
            wrapper_map = {
                'customer': 'Applicant',
                'address': 'Address',
                'demographics': 'Demographics',
                'employment': 'Employment'
            }
        elif path == '/v1/customer':
            operation_name = 'SaveCustomerInfo'
            wrapper_map = {
                'customer': 'Customer',
                'address': 'Address',
                'demographics': 'Demographics',
                'employment': 'Employment'
            }
        else:
            return {'statusCode': 404, 'body': 'Not Found'}

        # 3. Build SOAP Body Content
        soap_operation = ET.Element(operation_name)
        for key, wrapper_name in wrapper_map.items():
            if key in body:
                wrapper_element = ET.SubElement(soap_operation, wrapper_name)
                json_to_xml_elements(wrapper_element, body[key])

        # 4. Build WS-Security Header
        wsse_header = create_wsse_security_header(username, password)

        # 5. Assemble full SOAP envelope
        soap_envelope = build_soap_envelope(soap_operation, wsse_header)
        soap_payload = ET.tostring(soap_envelope, encoding='unicode', method='xml')
        
        print(f"SOAP Request Payload:\n{prettify_xml(soap_envelope)}")

        # 6. Call backend SOAP service
        headers = {
            'Content-Type': 'text/xml; charset=utf-8',
        }
        response = requests.post(BACKEND_URL, data=soap_payload, headers=headers, timeout=25)
        response.raise_for_status()

        # 7. Return backend response
        return {
            'statusCode': response.status_code,
            'headers': {
                'Content-Type': 'application/xml'
            },
            'body': response.text
        }

    except requests.exceptions.RequestException as e:
        print(f"Error calling backend: {e}")
        return {'statusCode': 502, 'body': f'Bad Gateway: {e}'}
    except Exception as e:
        print(f"An error occurred: {e}")
        return {'statusCode': 500, 'body': f'Internal Server Error: {e}'}
