#!/bin/python
import logging

import requests

from ocm_python_client.api_client import ApiClient
from ocm_python_client.configuration import Configuration
from ocm_python_client.exceptions import UnauthorizedException

from ocm_python_wrapper.exceptions import AuthenticationError, EndpointAccessError

API_URLS = {
    "stage": "https://api.stage.openshift.com",
    "production": "https://api.openshift.com",
}
LOGGER = logging.getLogger(__name__)


class OCMPythonClient(ApiClient):
    def __init__(
        self,
        token,
        base_api_url=API_URLS["production"],
        discard_unknown_keys=False,
    ):
        self.base_api_uri = base_api_url
        self.token = token

        self.client_config = Configuration(
            host=base_api_url,
            access_token=self.__confirm_auth(),
            discard_unknown_keys=discard_unknown_keys,
        )

        super().__init__(configuration=self.client_config)

    def __confirm_auth(self):
        endpoint = "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token"
        response = requests.post(
            endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": "cloud-services",
                "refresh_token": self.token,
            },
        )

        # TODO: Check which exceptions are needed
        if response.status_code != 200:
            if response.status_code == 400:
                if (
                    response.json().get("error_description")
                    == "Offline user session not found"
                ):
                    raise AuthenticationError(
                        f"""OFFLINE Token Expired! 
                        Please update your config with a new token from: https://cloud.redhat.com/openshift/token\n"
                        Error Code: {response.status_code}"""
                    )
            else:
                raise EndpointAccessError(err=response.status_code, endpoint=endpoint)

        return response.json()["access_token"]

    def call_api(self, *args, **kwargs):
        try:
            return super().call_api(*args, **kwargs)
        except UnauthorizedException:
            LOGGER.info("Refreshing client token.")
            self.client_config.access_token = self.__confirm_auth()
            return super().call_api(*args, **kwargs)
