import os
import fido
from email.utils import formataddr, parseaddr
from swagger_spec_validator.common import SwaggerValidationError
from bravado_core.formatter import SwaggerFormat
from bravado.client import SwaggerClient
from bravado.requests_client import RequestsClient  # sync + api key
from bravado.fido_client import FidoClient  # async
from bravado.http_future import HttpFuture
from bravado.swagger_model import Loader

NODE_ENV = os.environ.get('NODE_ENV')
GATEWAY_HOST = os.getenv('KERNEL_GATEWAY_HOST')
DEBUG = bool(
    (NODE_ENV and NODE_ENV == 'development') or
    (GATEWAY_HOST and 'localhost' not in GATEWAY_HOST)
)
client = None


def validate_email(email_string):
    try:
        formataddr(parseaddr(email_string))
    except Exception as ex:
        raise SwaggerValidationError(f'E-mail {email_string} is invalid')


email_format = SwaggerFormat(
    format='email', to_wire=str, to_python=str,
    validate=validate_email, description='e-mail address'
)


class FidoClientGlobalHeaders(FidoClient):
    def __init__(self, headers=None):
        super().__init__()
        self.headers = headers or {}

    def request(self, request_params, operation=None, request_config=None):
        request_for_twisted = self.prepare_request_for_twisted(request_params)
        request_for_twisted['headers'].update(self.headers)
        future_adapter = self.future_adapter_class(fido.fetch(**request_for_twisted))
        return HttpFuture(future_adapter, self.response_adapter_class, operation, request_config)


def load_client(apikey=None, headers=None):
    global client
    force = False

    if client is not None:
        http_client = client.swagger_spec.http_client
        force = bool(
            (apikey and http_client.authenticator.api_key != apikey) or \
            (headers is not None and http_client.headers != headers)
        )

    if force or client is None:
        # docker containers networking within docker-compose or Fargate task
        host = 'api.mpcontribs.org'
        if apikey is None:
            host = 'api:5000' if DEBUG else 'localhost:5000'

        if apikey:
            # TODO Kong forwards consumer headers when api-key used for auth
            http_client = RequestsClient()
            http_client.set_api_key(
                host, apikey, param_in='header', param_name='x-api-key'
            )
        else:
            # forward consumer headers when connecting through localhost
            http_client = FidoClientGlobalHeaders(headers=headers)

        loader = Loader(http_client)
        protocol = 'https' if apikey else 'http'
        spec_url = f'{protocol}://{host}/apispec.json'
        spec_dict = loader.load_spec(spec_url)
        spec_dict['host'] = host
        spec_dict['schemes'] = [protocol]
        client = SwaggerClient.from_spec(
            spec_dict, spec_url, http_client, {
                'validate_responses': False, 'use_models': False,
                'include_missing_properties': False, 'formats': [email_format]
            }
        )

    return client
