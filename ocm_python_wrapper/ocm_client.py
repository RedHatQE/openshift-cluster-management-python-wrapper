#!/bin/python
import logging

import requests
from ocm_python_client.api.default_api import DefaultApi

from ocm_python_client.api_client import ApiClient
from ocm_python_client.configuration import Configuration
from ocm_python_client.exceptions import UnauthorizedException

from ocm_python_wrapper.exceptions import AuthenticationError, EndpointAccessError


LOGGER = logging.getLogger(__name__)


class OCMPythonClient(ApiClient):
    def __init__(
        self,
        token,
        endpoint,
        api_host="production",
        discard_unknown_keys=False,
    ):
        self.endpoint = endpoint
        self.token = token
        self.client_config = Configuration(
            host=self.get_base_api_uri(api_host),
            access_token=self.__confirm_auth(),
            discard_unknown_keys=discard_unknown_keys,
        )

        super().__init__(configuration=self.client_config)

    def __confirm_auth(self):
        response = requests.post(
            self.endpoint,
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
                raise EndpointAccessError(err=response.status_code, endpoint=self.endpoint)

        return response.json()["access_token"]

    def call_api(self, *args, **kwargs):
        try:
            return super().call_api(*args, **kwargs)
        except UnauthorizedException:
            LOGGER.info("Refreshing client token.")
            self.client_config.access_token = self.__confirm_auth()
            return super().call_api(*args, **kwargs)

    @property
    def client(self):
        return DefaultApi(api_client=self)

    @staticmethod
    def get_base_api_uri(api_host):
        api_hosts_config = Configuration().get_host_settings()
        host_config = [host["url"] for host in api_hosts_config if host["description"].lower() == api_host]
        if not host_config:
            raise ValueError(f"Allowed configuration: {api_hosts_config}")
        return host_config[0]
