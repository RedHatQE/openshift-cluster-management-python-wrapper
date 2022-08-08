import logging

from ocm_python_client import ApiException
from ocm_python_client.model.upgrade_policy import UpgradePolicy

LOGGER = logging.getLogger(__name__)


def update_upgrade_policies(client, cluster, upgrade_policies_dict):
    LOGGER.info("Update cluster upgrade policies.")
    try:
        client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_post(
                cluster_id=cluster.cluster_id,
                upgrade_policy=UpgradePolicy(**upgrade_policies_dict),
        )
    except ApiException as ex:
        LOGGER.error(f"Fail to update upgrade policy {upgrade_policies_dict} on {ex.body}")
        raise


def delete_upgrade_policy(client, cluster, upgrade_policy_id):
    LOGGER.info(f"Delete upgrade policy {upgrade_policy_id}")
    try:
        client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_upgrade_policy_id_delete(
                cluster_id=cluster.cluster_id,
                upgrade_policy_id=upgrade_policy_id,
        )
    except ApiException as ex:
        LOGGER.error(f"Fail to delete upgrade policy {upgrade_policy_id} on {ex.body}")
        raise


def get_upgrade_policies(client, cluster):
    return client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_get(cluster_id=cluster.cluster_id).items


def get_upgrade_policy_id(client, cluster, upgrade_type="OSD"):
    LOGGER.info(f"Get upgrade policy id")
    cluster_upgrade_policies = get_upgrade_policies(client=client, cluster=cluster)
    upgrade_policy = [policy for policy in cluster_upgrade_policies if policy.upgrade_type == upgrade_type]
    assert upgrade_policy, f"Could not find a policy of {upgrade_type} type"
    return upgrade_policy[0]
