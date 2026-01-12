import re

def handler(event, context):
    """
    Lambda@Edge function to replicate a DataPower URLRewritePolicy.
    This function checks for a specific path and injects a SOAPAction header.
    """
    request = event['Records'][0]['cf']['request']
    uri = request['uri']
    
    print(f"Handling request for URI: {uri}")

    # Match pattern: /underwriting/quote/{id}
    # Regex from DataPower: ^/underwriting/quote/([A-Za-z0-9\-]+)$
    match = re.match(r'^/underwriting/quote/([A-Za-z0-9\-]+)$', uri)

    if match and request['method'] == 'POST':
        quote_id = match.group(1)
        print(f"Matched quote ID: {quote_id}. Injecting SOAPAction header.")

        # Inject the SOAPAction header
        request['headers']['soapaction'] = [
            {
                'key': 'SOAPAction',
                'value': '"insurance.com"' # The value includes quotes as in the DP config
            }
        ]
        
        # The path is not rewritten, it is passed through to the origin.
        # The origin is configured as the base path of the SOAP service.
        # CloudFront will forward the request to: https://backend.example.com/underwriting/quote/{id}
        # If the backend requires a path rewrite, it can be done here:
        # request['uri'] = '/soap/UnderwritingService'

    return request
