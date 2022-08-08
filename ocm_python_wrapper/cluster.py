import yaml
import logging

from ocm_python_wrapper.clusters import get_cluster_by_name
from ocm_python_wrapper.upgrade_policies import get_upgrade_policies

LOGGER = logging.getLogger(__name__)


class Cluster:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.cluster_id = self._cluster_id()

    def _cluster_id(self):
        return get_cluster_by_name(client=self.client, name=self.name)["id"]

    @property
    def instance(self):
        return self.client.api_clusters_mgmt_v1_clusters_cluster_id_get(cluster_id=self.cluster_id)

    @property
    def credentials(self):
        return self.client.api_clusters_mgmt_v1_clusters_cluster_id_credentials_get(
            cluster_id=self.cluster_id)

    @property
    def kubeconfig(self):
        return yaml.safe_load(self.credentials.kubeconfig)

    @property
    def upgrade_policies(self):
        return get_upgrade_policies(client=self.client, cluster=self)
