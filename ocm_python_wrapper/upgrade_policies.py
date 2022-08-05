import logging

from ocm_python_client import ApiException
from ocm_python_client.model.upgrade_policy import UpgradePolicy


LOGGER = logging.getLogger(__name__)


def get_cluster_upgrade_policies(client, cluster_id):
    return client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_get(
        cluster_id=cluster_id
    )


def set_cluster_upgrade_policies(client, upgrade_policies_dict):
    try:
        client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_post(
            cluster_id=upgrade_policies_dict["cluster_id"],
            upgrade_policy=UpgradePolicy(**upgrade_policies_dict),
        )
    except ApiException as ex:
        LOGGER.error(f"Fail to update upgrade policy {upgrade_policies_dict} on {ex.body}")
        raise
