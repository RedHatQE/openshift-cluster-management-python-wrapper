import json
import logging
from datetime import date, time

from ocm_python_client import ApiException
from ocm_python_client.model.upgrade_policy import UpgradePolicy

from ocm_python_wrapper.clusters import get_cluster_by_name


LOGGER = logging.getLogger(__name__)


class Cluster:
    def __init__(self, api_client, name):
        self.api_client = api_client
        self.name = name
        self.cluster_id = self._cluster_id()

    def _cluster_id(self):
        return get_cluster_by_name(api_client=self.api_client, name=self.name)["id"]

    @property
    def instance(self):
        return self.api_client.api_clusters_mgmt_v1_clusters_cluster_id_get(cluster_id=self.cluster_id)

    @property
    def credentials(self):
        return self.api_client.api_clusters_mgmt_v1_clusters_cluster_id_credentials_get(
            cluster_id=self.cluster_id)

    @property
    def kubeconfig(self):
        return self.credentials.kubeconfig

    @property
    def upgrade_policies(self):
        return self.api_client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_get(cluster_id=self.cluster_id).items

    def update_upgrade_policies(self, upgrade_policies_dict):
        try:
            self.api_client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_post(
                    cluster_id=self.cluster_id,
                    upgrade_policy=UpgradePolicy(**upgrade_policies_dict),
            )
        except ApiException as ex:
            LOGGER.error(f"Fail to update upgrade policy {upgrade_policies_dict} on {ex.body}")
            raise
