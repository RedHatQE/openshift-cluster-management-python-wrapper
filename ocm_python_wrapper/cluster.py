import logging

from ocm_python_client import ApiException
from ocm_python_client.model.upgrade_policy import UpgradePolicy

from ocm_python_wrapper.exceptions import MissingResourceError

LOGGER = logging.getLogger(__name__)


class Cluster:
    def __init__(self, api_client, name=None):
        self.api_client = api_client
        self.name = name
        self.cluster_id = self._cluster_id()

    def _cluster_id(self):
        cluster_info = self.api_client.api_clusters_mgmt_v1_clusters_get(
            search=f"name like '{self.name}%'"
        )
        if cluster_info:
            return cluster_info.items[0]["id"]
        raise MissingResourceError(name=self.name, kind="cluster")

    @property
    def instance(self):
        return self.api_client.api_clusters_mgmt_v1_clusters_cluster_id_get(
            cluster_id=self._cluster_id
        )

    @property
    def credentials(self):
        return self.api_client.api_clusters_mgmt_v1_clusters_cluster_id_credentials_get(
            cluster_id=self.cluster_id
        )._data_store

    @property
    def kubeconfig(self):
        return self.credentials["kubeconfig"]

    @property
    def upgrade_policies(self):
        return self.api_client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_get(cluster_id=self.cluster_id)

    def update_upgrade_policies(self, upgrade_policies_dict):
        try:
            self.api_client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_post(
                    cluster_id=self.cluster_id,
                    upgrade_policy=UpgradePolicy(**upgrade_policies_dict),
            )
        except ApiException as ex:
            LOGGER.error(f"Fail to update upgrade policy {upgrade_policies_dict} on {ex.body}")
            raise

    def addons(self):
        # TODO:  implement
        pass
