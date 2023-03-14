import os

import click

from ocm_python_wrapper.cluster import TIMEOUT_30MIN, ClusterAddOn
from ocm_python_wrapper.ocm_client import OCMPythonClient


@click.command()
@click.option("-a", "--addon", help="Addon name to install", required=True)
@click.option(
    "--timeout",
    help="Timeout in seconds to wait for addon to be installed/uninstalled",
    default=TIMEOUT_30MIN,
    show_default=True,
)
@click.option(
    "-e",
    "--endpoint",
    help="SSO endpoint url",
    default="https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
    show_default=True,
)
@click.option(
    "--action",
    help="Action to perform",
    required=True,
    type=click.Choice(["install", "uninstall"]),
)
@click.option(
    "-p",
    "--parameters",
    multiple=True,
    help="Addon parameters for installation. each parameter pass as id=value",
)
@click.option(
    "-t",
    "--token",
    help="OCM token (Taken from oc environment OCM_TOKEN if not passed)",
    required=True,
    default=os.environ.get("OCM_TOKEN"),
)
@click.option("-c", "--cluster", help="Cluster name", required=True)
@click.option(
    "--api-host",
    help="API host",
    default="production",
    type=click.Choice(["stage", "production"]),
    show_default=True,
)
def cli(addon, token, action, parameters, api_host, cluster, endpoint, timeout):
    _client = OCMPythonClient(
        token=token,
        endpoint=endpoint,
        api_host=api_host,
        discard_unknown_keys=True,
    ).client
    cluster_addon = ClusterAddOn(client=_client, cluster_name=cluster, addon_name=addon)

    install = action == "install"
    if install:
        _parameters = []
        for parameter in parameters:
            if "=" not in parameter:
                click.echo(f"parameters should be id=value, got {parameter}")
                raise click.Abort()

            _id, _value = parameter.split("=")
            _parameters.append({"id": _id, "value": _value})

        cluster_addon.install_addon(parameters=_parameters, wait_timeout=timeout)

    else:
        cluster_addon.uninstall_addon(wait_timeout=timeout)


if __name__ == "__main__":
    cli()
