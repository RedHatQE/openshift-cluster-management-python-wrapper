import os
from importlib.util import find_spec

import rosa.cli as rosa_cli
import yaml
from benedict import benedict
from clouds.aws.roles.roles import create_or_update_role_policy
from ocm_python_client import ApiException
from ocm_python_client.exceptions import NotFoundException
from ocm_python_client.model.add_on import AddOn
from ocm_python_client.model.add_on_installation import AddOnInstallation
from ocm_python_client.model.add_on_installation_parameter import (
    AddOnInstallationParameter,
)
from ocm_python_client.model.upgrade_policy import UpgradePolicy
from ocp_resources.constants import NOT_FOUND_ERROR_EXCEPTION_DICT
from ocp_resources.resource import ResourceEditor
from ocp_resources.rhmi import RHMI
from ocp_resources.utils import TimeoutExpiredError, TimeoutSampler
from ocp_utilities.infra import create_icsp, create_update_secret, get_client
from simple_logger.logger import get_logger

from ocm_python_wrapper.exceptions import MissingResourceError

LOGGER = get_logger(__name__)
TIMEOUT_10MIN = 10 * 60
TIMEOUT_30MIN = 30 * 60
SLEEP_1SEC = 1


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
        self.hypershift = self.is_hypershift

    def _cluster_id(self):
        cluster_list = self.client.api_clusters_mgmt_v1_clusters_get(
            search=f"name like '{self.name}'"
        ).items
        if cluster_list:
            return cluster_list[0].id
        raise MissingResourceError(name=self.name, kind="cluster")

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
        kubeconfig = yaml.safe_load(self.credentials.kubeconfig)
        # TODO: Remove once https://issues.redhat.com/browse/OCPBUGS-8101 is resolved
        if self.hypershift:
            del kubeconfig["clusters"][0]["cluster"]["certificate-authority-data"]
        return kubeconfig

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

    @property
    def is_hypershift(self):
        return self.instance.hypershift.enabled is True

    def delete(self, wait=True, timeout=1800):
        LOGGER.info(f"Delete cluster {self.name}.")
        self.client.api_clusters_mgmt_v1_clusters_cluster_id_delete(
            cluster_id=self.cluster_id
        )
        if wait:
            self.wait_for_cluster_deletion(wait_timeout=timeout)

    def wait_for_cluster_deletion(self, wait_timeout=TIMEOUT_30MIN):
        LOGGER.info(f"Wait for cluster {self.name} to be deleted.")
        try:
            for sample in TimeoutSampler(
                wait_timeout=wait_timeout,
                sleep=SLEEP_1SEC,
                func=lambda: self.exists,
            ):
                if not sample:
                    return
        except TimeoutExpiredError:
            LOGGER.error(f"Timeout waiting for cluster {self.name} to be deleted")
            raise

    def wait_for_cluster_ready(self, wait_timeout=TIMEOUT_30MIN):
        LOGGER.info(f"Wait for cluster {self.name} to be ready.")
        try:
            for sample in TimeoutSampler(
                wait_timeout=wait_timeout,
                sleep=SLEEP_1SEC,
                func=lambda: self.instance,
            ):
                if sample and str(sample.state) == "ready":
                    return True
        except TimeoutExpiredError:
            LOGGER.error("Timeout waiting for cluster to be ready")
            raise

    @property
    def exists(self):
        """
        Returns cluster instance if cluster exists else returns None
        """
        try:
            return self.instance
        except NotFoundException:
            return None

    @property
    def cloud_provider(self):
        return self.instance.cloud_provider.id if self.exists else None


class ClusterAddOn(Cluster):
    """
    manage cluster addon

    Example:
         _client = OCMPythonClient(
        token=os.environ["OCM_TOKEN"],
        endpoint="https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
        api_host="stage",
        discard_unknown_keys=True,
        ).client
        cluster_addon = ClusterAddOn(
            client=_client, cluster_name="cluster-name", addon_name="ocm-addon-test-operator"
        )
        parameters = [
            {"id": "has-external-resources", "value": "false"},
            {"id": "aws-cluster-test-param", "value": "false"},
        ]
        cluster_addon.install_addon(parameters=parameters)
        cluster_addon.uninstall_addon()

    """

    class State:
        INSTALLING = "installing"
        READY = "ready"

    def __init__(self, client, cluster_name, addon_name):
        super().__init__(client=client, name=cluster_name)
        self.addon_name = addon_name
        self.addon_version = self.addon_info()["version"]["id"]

    def addon_info(self):
        return self.client.api_clusters_mgmt_v1_addons_addon_id_get(
            self.addon_name
        ).to_dict()

    def validate_and_update_addon_parameters(
        self, user_parameters, use_api_defaults=True
    ):
        """Validate and update user input parameters against API's conditions and requirements.

        Args:
            user_parameters (List): User parameters
                Example:
                    parameters = [{"id": "has-external-resources", "value": "false"},
                                    {"id": "aws-cluster-test-param", "value": "false"},]
            use_api_defaults (bool): If true, set required parameter (which are not part of `user_parameters`) with
                                            default value to not fail as missing.

        Returns:
            List: Updated parameters (if default values updated) to provide for installation.

        Raises:
            ValueError: When a required parameter is missing,
                        or when parameters are passed but not needed for addon.
        """

        def _get_required_cluster_parameters(_addon_parameters):
            """Filter cluster-related ``addon parameters``

            Args:
                _addon_parameters (dict) : Addons parameters from Clusters Management
            ``cluster_mgmt_v1_addons_addon_id`` API.

            Returns:
                Dict of required parameters which are relevant for the cluster's configuration
                example:
                _required_parameters = {'cidr-range': {'default_value': '10.1.0.0/26'}, 'addon_parameter': {
                        'default_value': ''}, ..}

            """
            _required_parameters = {}

            for param in _addon_parameters["items"]:
                param_conditions = [
                    condition["data"]
                    for condition in param.get("conditions", [])
                    if param.get("required") and condition["resource"] == "cluster"
                ]
                if param_conditions:
                    for condition, condition_value in param_conditions[0].items():
                        if not self.check_param_conditions(
                            clusters_dict=self.instance.to_dict(),
                            condition=condition,
                            condition_value=condition_value,
                        ):
                            break
                    else:
                        _required_parameters[param["id"]] = {
                            "default_value": param.get("default_value")
                        }
            return _required_parameters

        _info = self.addon_info()
        addon_parameters = _info.get("parameters")
        if not addon_parameters and user_parameters:
            raise ValueError(f"{self.addon_name} does not take any parameters")

        required_parameters = _get_required_cluster_parameters(
            _addon_parameters=addon_parameters
        )
        user_addon_parameters = [param["id"] for param in user_parameters]
        missing_parameter = []

        for param, param_dict in required_parameters.items():
            if param not in user_addon_parameters:
                if use_api_defaults and param_dict["default_value"]:
                    user_parameters.append(
                        {
                            "id": param,
                            "value": param_dict["default_value"],
                        }
                    )
                else:
                    missing_parameter.append(param)

        if missing_parameter:
            raise ValueError(
                f"{self.addon_name} missing some required parameters {missing_parameter}"
            )
        return user_parameters

    def install_addon(
        self,
        parameters=None,
        wait=True,
        wait_timeout=TIMEOUT_30MIN,
        brew_token=None,
        rosa=False,
        use_api_defaults=True,
    ):
        """
        Install addon on the cluster

        Args:
            parameters (list): List of dict.
            wait (bool): True to wait for addon to be installed.
            wait_timeout (int): Timeout in seconds to wait for addon to be installed.
            brew_token (str): brew token for creating brew pull secret
            rosa (bool): Use ROSA cli if True else use OCM API
            use_api_defaults (bool): Use addon parameter default value if not provided.

         Returns:
            AddOnInstallation or list: list of stdout responses if rosa is True, else AddOnInstallation
        """
        addon = AddOn(id=self.addon_name)
        _addon_installation_dict = {
            "id": self.addon_name,
            "addon": addon,
        }

        parameters = self.validate_and_update_addon_parameters(
            user_parameters=parameters, use_api_defaults=use_api_defaults
        )
        if (
            self.addon_name == "managed-odh"
            and "stage" in self.client.api_client.configuration.host
        ):
            self.create_rhods_brew_config(brew_token=brew_token)
        LOGGER.info(f"Installing addon {self.addon_name} v{self.addon_version}")
        if rosa:
            params_command = ""
            for parameter in parameters:
                params_command += f" --{parameter['id']} {parameter['value']}"
            res = rosa_cli.execute(
                command=f"install addon {self.addon_name} --cluster {self.name} {params_command}"
            )
        else:
            if parameters:
                _parameters = []
                for params in parameters:
                    _parameters.append(
                        AddOnInstallationParameter(
                            id=params["id"], value=params["value"]
                        )
                    )

                _addon_installation_dict["parameters"] = {"items": _parameters}
            res = self.client.api_clusters_mgmt_v1_clusters_cluster_id_addons_post(
                cluster_id=self.cluster_id,
                add_on_installation=AddOnInstallation(
                    _check_type=False, **_addon_installation_dict
                ),
            )

        if (
            self.addon_name == "managed-api-service"
            and "stage" in self.client.api_client.configuration.host
        ):
            # Create role-policy for RHOAM installation:
            # https://access.redhat.com/documentation/en-us/red_hat_openshift_api_management/1/guide/53dfb804-2038-4545-b917-2cb01a09ef98#_b5f80fce-73cb-4869-aa16-763bbe09896a:~:text=In%20the%20AWS%20CLI%2C%20create%20a%20policy%20for%20SRE%20Support.%20Enter%20the%20following%3A
            with open(
                os.path.join(
                    find_spec("ocm_python_wrapper").submodule_search_locations[0],
                    "manifests/managed-api-service-policy.json",
                ),
                "r",
            ) as fd:
                policy_document = fd.read()
            create_or_update_role_policy(
                role_name="ManagedOpenShift-Support-Role",
                policy_name="rhoam-sre-support-policy",
                policy_document=policy_document,
            )
            self.update_rhoam_cluster_storage_config()

        if wait:
            self.wait_for_install_state(
                state=self.State.READY, wait_timeout=wait_timeout
            )

        LOGGER.info(f"{self.addon_name} v{self.addon_version} successfully installed")
        return res

    def addon_installation_instance(self):
        try:
            return self.client.api_clusters_mgmt_v1_clusters_cluster_id_addons_addoninstallation_id_get(
                cluster_id=self.cluster_id, addoninstallation_id=self.addon_name
            )
        except NotFoundException:
            LOGGER.info(f"{self.addon_name} not found")
            return

    def addon_installation_instance_sampler(self, wait_timeout=TIMEOUT_30MIN):
        return TimeoutSampler(
            wait_timeout=wait_timeout,
            sleep=SLEEP_1SEC,
            func=self.addon_installation_instance,
        )

    def wait_for_install_state(self, state, wait_timeout=TIMEOUT_30MIN):
        _state = None
        try:
            for (
                _addon_installation_instance
            ) in self.addon_installation_instance_sampler(wait_timeout=wait_timeout):
                _state = str(_addon_installation_instance.get("state"))
                if _state == state:
                    return True
        except TimeoutExpiredError:
            LOGGER.error(
                f"Timeout waiting for {self.addon_name} state to be {state}, last state was {_state}"
            )
            raise

    def uninstall_addon(self, wait=True, wait_timeout=TIMEOUT_30MIN, rosa=False):
        """
        Uninstall addon on the cluster

        Args:
            wait (bool): True to wait for addon to be installed.
            wait_timeout (int): Timeout in seconds to wait for addon to be installed.
            rosa (bool): Use ROSA cli if True else use OCM API

        Returns:
            None or list: list of stdout responses if rosa is True, else None.
        """
        LOGGER.info(f"Removing addon {self.addon_name} v{self.addon_version}")
        if rosa:
            res = rosa_cli.execute(
                command=f"uninstall addon {self.addon_name} --cluster {self.name}"
            )
        else:
            res = self.client.api_clusters_mgmt_v1_clusters_cluster_id_addons_addoninstallation_id_delete(
                cluster_id=self.cluster_id,
                addoninstallation_id=self.addon_name,
            )
        if wait:
            for (
                _addon_installation_instance
            ) in self.addon_installation_instance_sampler(wait_timeout=wait_timeout):
                if not _addon_installation_instance:
                    return True
        LOGGER.info(f"{self.addon_name} v{self.addon_version} was successfully removed")
        return res

    @staticmethod
    def update_rhoam_cluster_storage_config():
        def _wait_for_rhmi_resource():
            for rhmi_sample in TimeoutSampler(
                wait_timeout=TIMEOUT_30MIN,
                sleep=SLEEP_1SEC,
                func=lambda: RHMI(name="rhoam", namespace="redhat-rhoam-operator"),
                exceptions_dict={
                    NotImplementedError: [],
                    **NOT_FOUND_ERROR_EXCEPTION_DICT,
                },
            ):
                if rhmi_sample and rhmi_sample.exists:
                    return rhmi_sample

        rhmi = _wait_for_rhmi_resource()
        ResourceEditor(
            patches={rhmi: {"spec": {"useClusterStorage": "false"}}}
        ).update()

    @staticmethod
    def create_rhods_brew_config(brew_token):
        create_icsp(
            icsp_name="brew-registry",
            repository_digest_mirrors=[
                {
                    "source": "registry.redhat.io/rhods",
                    "mirrors": ["brew.registry.redhat.io/rhods"],
                }
            ],
        )
        secret_data_dict = {"auths": {"brew.registry.redhat.io": {"auth": brew_token}}}
        create_update_secret(
            secret_data_dict=secret_data_dict,
            name="pull-secret",  # pragma: allowlist secret
            namespace="openshift-config",
        )

    @staticmethod
    def check_param_conditions(clusters_dict, condition, condition_value):
        """
        Check if parameter conditions met with cluster configuration

        Args:
            clusters_dict (dict): Cluster instance dict
            condition (str): Condition key to check
            condition_value (str): Condition expected value

        Returns:
            Bool: True if cluster instance match with condition, else False

        """
        cluster_condition_value = benedict(clusters_dict, keypath_separator=".").get(
            condition
        )
        return (
            isinstance(condition_value, list)
            and cluster_condition_value in condition_value
        ) or cluster_condition_value == condition_value
