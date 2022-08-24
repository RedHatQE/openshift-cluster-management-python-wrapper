import logging

import yaml
from ocm_python_client import ApiException
from ocm_python_client.model.upgrade_policy import UpgradePolicy
from ocp_resources.resource import get_client
from ocp_resources.utils import TimeoutExpiredError, TimeoutSampler

from ocm_python_wrapper.exceptions import MissingResourceError


LOGGER = logging.getLogger(__name__)
TIMEOUT_10MIN = 10 * 60


class Clusters:
    def __init__(self, client):
        self.client = client

    def get(self):
        clusters_list = self.client.api_clusters_mgmt_v1_clusters_get()
        for cluster in clusters_list.items:
            yield Cluster(client=self.client, name=cluster.name)


class Cluster:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.cluster_id = self._cluster_id()

    def _cluster_id(self):
        cluster_list = self.client.api_clusters_mgmt_v1_clusters_get(
            search=f"name like '{self.name}'"
        ).items
        if cluster_list:
            return cluster_list[0].id
        raise MissingResourceError(name=self.name, kind=self.__class__.__name__)

    @property
    def instance(self):
        return self.client.api_clusters_mgmt_v1_clusters_cluster_id_get(
            cluster_id=self.cluster_id
        )

    # Cluster credentials
    @property
    def credentials(self):
        return self.client.api_clusters_mgmt_v1_clusters_cluster_id_credentials_get(
            cluster_id=self.cluster_id
        )

    @property
    def kubeconfig(self):
        return yaml.safe_load(self.credentials.kubeconfig)

    @property
    def ocp_client(self):
        return get_client(config_dict=self.kubeconfig)

    # Cluster version
    def wait_for_ocm_cluster_version(self, ocp_target_version):
        LOGGER.info(
            f"Wait for cluster {self.name} version to be {ocp_target_version} in OCM."
        )
        samples = TimeoutSampler(
            wait_timeout=TIMEOUT_10MIN,
            sleep=10,
            func=lambda: self.instance.version.raw_id == ocp_target_version,
        )
        try:
            for sample in samples:
                if sample:
                    return
        except TimeoutExpiredError:
            LOGGER.error(
                f"Cluster {self.name} version {self.instance.version.raw_id} does not match "
                f"expected {ocp_target_version} version"
            )
            raise

    # Upgrade policies
    @property
    def upgrade_policies(self):
        return (
            self.client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_get(
                cluster_id=self.cluster_id
            ).items
        )

    def update_upgrade_policies(
        self, upgrade_policies_dict, wait=False, wait_timeout=TIMEOUT_10MIN
    ):
        LOGGER.info("Update cluster upgrade policies.")
        try:
            self.client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_post(
                cluster_id=self.cluster_id,
                upgrade_policy=UpgradePolicy(**upgrade_policies_dict),
            )
            if wait:
                self.wait_for_updated_upgrade_policy(
                    ocp_target_version=upgrade_policies_dict["version"],
                    wait_timeout=wait_timeout,
                )
        except ApiException as ex:
            LOGGER.error(
                f"Fail to update upgrade policy {upgrade_policies_dict} on {ex.body}"
            )
            raise

    def delete_upgrade_policy(self, upgrade_policy_id):
        LOGGER.info(f"Delete upgrade policy {upgrade_policy_id}")
        try:
            self.client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_upgrade_policy_id_delete(
                cluster_id=self.cluster_id,
                upgrade_policy_id=upgrade_policy_id,
            )
        except ApiException as ex:
            LOGGER.error(
                f"Fail to delete upgrade policy {upgrade_policy_id} on {ex.body}"
            )
            raise

    def get_upgrade_policy_id(self, upgrade_type="OSD"):
        LOGGER.info("Get upgrade policy id")
        upgrade_policy = [
            policy
            for policy in self.upgrade_policies
            if policy.upgrade_type == upgrade_type
        ]
        assert upgrade_policy, f"Could not find a policy of {upgrade_type} type"
        return upgrade_policy[0]

    def wait_for_updated_upgrade_policy(
        self, ocp_target_version, wait_timeout=TIMEOUT_10MIN
    ):
        LOGGER.info(
            f"Wait for cluster {self.name} upgrade policy to be updated with {ocp_target_version} version."
        )
        samples = TimeoutSampler(
            wait_timeout=wait_timeout,
            sleep=1,
            func=lambda: self.upgrade_policies,
        )
        try:
            for sample in samples:
                if sample and sample[0].version == ocp_target_version:
                    LOGGER.info(f"Upgrade policy updated: {sample}")
                    return
        except TimeoutExpiredError:
            LOGGER.error("Upgrade policy was not updated")
            raise
