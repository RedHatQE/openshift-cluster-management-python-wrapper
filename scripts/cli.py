import os

import click

from ocm_python_wrapper.cluster import ClusterAddOn
from ocm_python_wrapper.ocm_client import OCMPythonClient


@click.command()
@click.option("-a", "--addon", help="Addon name to install", required=True)
@click.option(
    "-p",
    "--parameters",
    multiple=True,
    help="Addon parameters for installation. each parameter pass as id=value",
)
@click.option("-i", "--install", help="Install the addon", default=False, is_flag=True)
@click.option(
    "-u", "--uninstall", help="Uninstall the addon", default=False, is_flag=True
)
@click.option(
    "-t",
    "--token",
    help="OCM token",
    required=True,
    default=os.environ.get("OCM_TOKEN"),
)
@click.option("-c", "--cluster", help="Cluster name", required=True)
@click.option(
    "-e",
    "--api-host",
    help="API host",
    default="production",
    type=click.Choice(["stage", "production"]),
)
def cli(addon, token, install, uninstall, parameters, api_host, cluster):
    click.echo(f"Addon: {addon}")
    click.echo(f"token: {token}")
    click.echo(f"install: {install}")
    click.echo(f"uninstall: {uninstall}")
    click.echo(f"Parameters: {parameters}")
    click.echo(f"api_host: {api_host}")
    click.echo(f"cluster: {cluster}")

    _client = OCMPythonClient(
        token=token,
        endpoint="https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
        api_host=api_host,
        discard_unknown_keys=True,
    ).client
    cluster_addon = ClusterAddOn(client=_client, cluster_name=cluster, addon_name=addon)
    if install:
        _parameters = []
        for parameter in parameters:
            _id, _value = parameter.split("=")
            _parameters.append({"id": _id, "value": _value})

        cluster_addon.install_addon(parameters=_parameters)

    elif uninstall:
        cluster_addon.remove_addon()


if __name__ == "__main__":
    cli()
