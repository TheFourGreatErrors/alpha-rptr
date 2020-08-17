#!/usr/bin/env python

from urllib.parse import urlparse

import time, hashlib, hmac

from bravado.client import SwaggerClient
from bravado.requests_client import RequestsClient, Authenticator
from bravado.swagger_model import Loader

# swagger spec's formats to exclude. this help to avoid warning in your console.
EXCLUDE_SWG_FORMATS = ['JSON', 'guid']


class APIKeyAuthenticator(Authenticator):

    def __init__(self, host, api_key, api_secret):
        super(APIKeyAuthenticator, self).__init__(host)
        self.api_key = api_key
        self.api_secret = api_secret

    def matches(self, url):
        if 'swagger.json' in url:
            return False
        return True

    def apply(self, r):
        # 5s grace period in case of clock skew
        expires = int(time.time() * 1000)
        r.headers['api-expires'] = str(expires)
        r.headers['api-key'] = self.api_key
        prepared = r.prepare()
        body = prepared.body or ''
        url = prepared.path_url
        r.headers['api-signature'] = self.generate_signature(self.api_secret, r.method, url, expires, body)
        return r

    def generate_signature(self, secret, verb, url, nonce, data):
        parsedURL = urlparse(url)
        path = parsedURL.path
        if parsedURL.query:
            path = path + '?' + parsedURL.query

        nonce = str(nonce)
        _message = verb + path + nonce + data

        message = bytes(_message.encode('utf-8'))
        secret = bytes(secret.encode('utf-8'))

        return hmac.new(secret, message, digestmod=hashlib.sha256).hexdigest()


def bitmex_api(test=True, config=None, api_key=None, api_secret=None):
    # config options at http://bravado.readthedocs.io/en/latest/configuration.html
    if not config:
        config = {
            # Don't use models (Python classes) instead of dicts for #/definitions/{models}
            'use_models': False,
            # bravado has some issues with nullable fields
            'validate_responses': False,
            # Returns response in 2-tuple of (body, response); if False, will only return body
            'also_return_response': True,

            # 'validate_swagger_spec': True,
            # 'validate_requests': True,
            # 'formats': [],
        }

    host = 'https://www.bitmex.com'
    if test:
        host = 'https://testnet.bitmex.com'

    spec_uri = host + '/api/explorer/swagger.json'
    spec_dict = get_swagger_json(spec_uri, exclude_formats=EXCLUDE_SWG_FORMATS)

    if api_key and api_secret:
        request_client = RequestsClient()
        request_client.authenticator = APIKeyAuthenticator(host, api_key, api_secret)
        return SwaggerClient.from_spec(spec_dict, origin_url=spec_uri, http_client=request_client, config=config)
    else:
        return SwaggerClient.from_spec(spec_dict, origin_url=spec_uri, http_client=None, config=config)


# exclude some format from swagger json to avoid warning in API execution.
def get_swagger_json(spec_uri, exclude_formats=[]):
    loader = Loader(RequestsClient())
    spec_dict = loader.load_spec(spec_uri)
    if not exclude_formats:
        return spec_dict

    # exlude formats from definitions
    for def_key, def_item in spec_dict['definitions'].items():
        if 'properties' not in def_item:
            continue
        for prop_key, prop_item in def_item['properties'].items():
            if 'format' in prop_item and prop_item['format'] in exclude_formats:
                prop_item.pop('format')

    # exlude formats from paths
    for path_key, path_item in spec_dict['paths'].items():
        for method_key, method_item in path_item.items():
            if 'parameters' not in method_item:
                continue
            for param in method_item['parameters']:
                if 'format' in param and param['format'] in exclude_formats:
                    param.pop('format')
    return spec_dict
