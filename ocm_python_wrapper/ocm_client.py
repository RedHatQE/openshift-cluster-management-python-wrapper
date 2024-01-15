#!/bin/python

import requests
from ocm_python_client.api.default_api import DefaultApi
from ocm_python_client.api_client import ApiClient
from ocm_python_client.configuration import Configuration
from ocm_python_client.exceptions import UnauthorizedException
from simple_logger.logger import get_logger

from ocm_python_wrapper.exceptions import AuthenticationError, EndpointAccessError

LOGGER = get_logger(name=__name__)


class OCMPythonClient(ApiClient):
    """
    A client for interacting with the OpenShift Cluster Manager (OCM).
    """

    def __init__(
        self,
        token,
        endpoint,
        api_host="production",
        discard_unknown_keys=False,
    ):
        """
        Initializes the OCM client.

        Args:
            token (str): The authentication token.
            endpoint (str): The endpoint to connect to.
            api_host (str, optional): The API host to use. Defaults to "production".
            discard_unknown_keys (bool, optional): Whether to discard unknown keys in the response. Defaults to False.
        """
        self.endpoint = endpoint
        self.token = token
        self.client_config = Configuration(
            host=self.get_base_api_uri(api_host),
            access_token=self.__confirm_auth(),
            discard_unknown_keys=discard_unknown_keys,
        )

        super().__init__(configuration=self.client_config)

    def __confirm_auth(self):
        """
        Confirms the authentication by making a POST request to the endpoint.

        Returns:
            str: The access token.

        Raises:
            AuthenticationError: If the token is expired.
            EndpointAccessError: If the endpoint cannot be accessed.
        """
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
                if response.json().get("error_description") == "Offline user session not found":
                    raise AuthenticationError(f"""OFFLINE Token Expired!
                        Please update your config with a new token from: https://cloud.redhat.com/openshift/token\n"
                        Error Code: {response.status_code}""")
            else:
                raise EndpointAccessError(err=response.status_code, endpoint=self.endpoint)

        return response.json()["access_token"]

    def call_api(self, *args, **kwargs):
        """
        Calls the API with the given arguments and keyword arguments.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            The response from the API call.

        Raises:
            UnauthorizedException: If the client is unauthorized.
        """
        try:
            return super().call_api(*args, **kwargs)
        except UnauthorizedException:
            LOGGER.warning("Refreshing client token.")
            self.client_config.access_token = self.__confirm_auth()
            return super().call_api(*args, **kwargs)

    @property
    def client(self):
        """
        Returns the default API client.

        Returns:
            DefaultApi: The default API client.
        """
        return DefaultApi(api_client=self)

    @staticmethod
    def get_base_api_uri(api_host):
        """
        Gets the base API URI for the given API host.

        Args:
            api_host (str): The API host.

        Returns:
            str: The base API URI.

        Raises:
            ValueError: If the API host is not found in the configuration.
        """
        api_hosts_config = Configuration().get_host_settings()
        host_config = [host["url"] for host in api_hosts_config if host["description"].lower() == api_host]
        if host_config:
            return host_config[0]
        raise ValueError(f"Allowed configuration: {api_hosts_config}")
