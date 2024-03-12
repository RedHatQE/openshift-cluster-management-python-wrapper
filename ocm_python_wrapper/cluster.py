import functools
import inspect
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
from ocp_resources.image_content_source_policy import ImageContentSourcePolicy
from ocp_resources.job import Job
from ocp_resources.resource import ResourceEditor
from ocp_resources.rhmi import RHMI
from timeout_sampler import TimeoutExpiredError, TimeoutSampler, TimeoutWatch
from ocp_utilities.infra import create_update_secret, get_client
from simple_logger.logger import get_logger
from ocp_utilities.must_gather import collect_must_gather

from ocm_python_wrapper.exceptions import MissingResourceError

LOGGER = get_logger(name=__name__)
TIMEOUT_5MIN = 5 * 60
TIMEOUT_10MIN = 10 * 60
TIMEOUT_30MIN = 30 * 60
TIMEOUT_45MIN = 45 * 60
TIMEOUT_60MIN = 60 * 60
SLEEP_1SEC = 1
AWS_OSD_STR = "aws"
GCP_OSD_STR = "gcp"


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
        try:
            self.cluster_id = self._cluster_id()
        except MissingResourceError:
            self.cluster_id = None

    def _cluster_id(self):
        cluster_list = self.client.api_clusters_mgmt_v1_clusters_get(search=f"name like '{self.name}'").items
        if cluster_list:
            return cluster_list[0].id
        raise MissingResourceError(name=self.name, kind="cluster")

    @property
    def instance(self):
        if not self.cluster_id:
            self.cluster_id = self._cluster_id()

        return self.client.api_clusters_mgmt_v1_clusters_cluster_id_get(cluster_id=self.cluster_id)

    # Cluster credentials
    @property
    def credentials(self):
        return self.client.api_clusters_mgmt_v1_clusters_cluster_id_credentials_get(cluster_id=self.cluster_id)

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
        LOGGER.info(f"Wait for cluster {self.name} version to be {ocp_target_version} in OCM.")
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
                f"Cluster {self.name} version {self.instance.version.raw_id} does not"
                f" match expected {ocp_target_version} version"
            )
            raise

    # Upgrade policies
    @property
    def upgrade_policies(self):
        return self.client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_get(
            cluster_id=self.cluster_id
        ).items

    def update_upgrade_policies(self, upgrade_policies_dict, wait=False, wait_timeout=TIMEOUT_10MIN):
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
            LOGGER.error(f"Fail to update upgrade policy {upgrade_policies_dict} on {ex.body}")
            raise

    def delete_upgrade_policy(self, upgrade_policy_id):
        LOGGER.info(f"Delete upgrade policy {upgrade_policy_id}")
        try:
            self.client.api_clusters_mgmt_v1_clusters_cluster_id_upgrade_policies_upgrade_policy_id_delete(
                cluster_id=self.cluster_id,
                upgrade_policy_id=upgrade_policy_id,
            )
        except ApiException as ex:
            LOGGER.error(f"Fail to delete upgrade policy {upgrade_policy_id} on {ex.body}")
            raise

    def get_upgrade_policy_id(self, upgrade_type="OSD"):
        LOGGER.info("Get upgrade policy id")
        upgrade_policy = [policy for policy in self.upgrade_policies if policy.upgrade_type == upgrade_type]
        assert upgrade_policy, f"Could not find a policy of {upgrade_type} type"
        return upgrade_policy[0]

    def wait_for_updated_upgrade_policy(self, ocp_target_version, wait_timeout=TIMEOUT_10MIN):
        LOGGER.info(f"Wait for cluster {self.name} upgrade policy to be updated with {ocp_target_version} version.")
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
    @functools.cache
    def hypershift(self):
        return self.instance.hypershift.enabled is True

    def delete(self, wait=True, timeout=1800, deprovision=True):
        if not self.cluster_id:
            raise MissingResourceError(kind="Cluster", name=self.name)

        LOGGER.info(f"Delete cluster {self.name}.")
        self.client.api_clusters_mgmt_v1_clusters_cluster_id_delete(cluster_id=self.cluster_id, deprovision=deprovision)
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

    def wait_for_cluster_ready(self, wait_timeout=TIMEOUT_30MIN, stop_status=None, wait_for_osd_job=True):
        stop_status = stop_status or "error"
        time_watcher = TimeoutWatch(timeout=wait_timeout)

        try:
            LOGGER.info(f"Wait for cluster {self.name} to be exists.")
            self.wait_exists(wait_timeout=wait_timeout)
        except TimeoutExpiredError:
            LOGGER.error(f"Timeout waiting for cluster {self.name} to be exists")
            raise

        cluster_status_str = "Status of cluster {name} is {current_status}"
        try:
            LOGGER.info(f"Wait for cluster {self.name} to be ready.")
            cluster_status = None
            for sample in TimeoutSampler(
                wait_timeout=time_watcher.remaining_time(),
                sleep=SLEEP_1SEC,
                func=lambda: self.instance,
            ):
                if sample:
                    current_status = str(sample.state)
                    if current_status == "ready":
                        break
                    elif current_status != cluster_status:
                        cluster_status = current_status
                        LOGGER.info(cluster_status_str.format(name=self.name, current_status=current_status))
                    elif current_status == stop_status:
                        raise TimeoutExpiredError(
                            cluster_status_str.format(name=self.name, current_status=current_status)
                        )

        except TimeoutExpiredError:
            LOGGER.error(f"Timeout waiting for cluster {self.name} to be ready")
            raise

        if wait_for_osd_job and not self.hypershift:
            self.wait_for_osd_cluster_ready_job(wait_timeout=time_watcher.remaining_time())

        return self

    @property
    def exists(self):
        """
        Returns cluster instance if cluster exists else returns None
        """
        try:
            return self.instance
        except (NotFoundException, MissingResourceError):
            return None

    def wait_exists(self, wait_timeout):
        for sample in TimeoutSampler(
            wait_timeout=wait_timeout,
            sleep=1,
            func=lambda: self.exists,
        ):
            if sample:
                return sample

    @property
    def cloud_provider(self):
        return self.instance.cloud_provider.id if self.exists else None

    @property
    @functools.cache
    def rosa(self):
        return self.instance.get(AWS_OSD_STR, {}).get("tags", {}).get("red-hat-clustertype") == "rosa"

    @property
    @functools.cache
    def region(self):
        return self.instance.get("region", {}).get("id")

    @property
    def kubeadmin_password(self):
        return self.credentials.admin.password

    def osd_dict(
        self,
        region,
        ocp_version,
        aws_access_key_id=None,
        aws_account_id=None,
        aws_secret_access_key=None,
        replicas=2,
        compute_machine_type="m5.4xlarge",
        multi_az=False,
        channel_group="stable",
        expiration_time=None,
        platform=None,
        gcp_service_account=None,
    ):
        """
        Constructs a dictionary with the configuration for an OSD AWS cluster.

        Args:
            region (str): The region where the cluster will be deployed.
            ocp_version (str): The OpenShift version for the cluster.
            aws_access_key_id (str): The AWS access key ID.
            aws_account_id (str): The AWS account ID.
            aws_secret_access_key (str): The AWS secret access key.
            replicas (int, optional): The number of replicas for the cluster. Defaults to 2.
            compute_machine_type (str, optional): The type of compute machine for the cluster. Defaults to "m5.4xlarge".
            multi_az (bool, optional): Whether to use multiple availability zones. Defaults to False.
            channel_group (str, optional): The channel group for the cluster. Defaults to "stable".
            expiration_time (str, optional): The expiration time for the cluster. Defaults to None.
                Example: f"{(datetime.now() + timedelta(seconds=3600)).isoformat()}Z"
            platform (str): Target cluster platform. Supported: "aws" and "gpc"
            gcp_service_account (dict, optional): GCP service account dict. Defaults to None.

        Returns:
            dict: A dictionary with the configuration for an OSD AWS cluster.
        """
        _cluster_dict = {
            "name": self.name,
            "region": {"id": region},
            "nodes": {
                "compute_machine_type": {"id": compute_machine_type},
                "compute": replicas,
            },
            "managed": True,
            "product": {"id": "osd"},
            "cloud_provider": {"id": platform},
            "multi_az": multi_az,
            "etcd_encryption": True,
            "disable_user_workload_monitoring": True,
            "version": {
                "id": f"openshift-v{ocp_version}",
                "channel_group": channel_group,
            },
            "properties": {"use_local_credentials": "true"},
            "ccs": {"enabled": True, "disable_scp_checks": False},
        }

        if platform == AWS_OSD_STR:
            _cluster_dict[AWS_OSD_STR] = {
                "access_key_id": aws_access_key_id,
                "account_id": aws_account_id,
                "secret_access_key": aws_secret_access_key,
            }

        elif platform == GCP_OSD_STR:
            _cluster_dict[GCP_OSD_STR] = gcp_service_account

        if expiration_time:
            _cluster_dict["expiration_time"] = expiration_time

        return _cluster_dict

    def provision_osd(
        self,
        region=None,
        ocp_version=None,
        aws_access_key_id=None,
        aws_account_id=None,
        aws_secret_access_key=None,
        replicas=2,
        compute_machine_type="m5.4xlarge",
        multi_az=False,
        channel_group="stable",
        expiration_time=None,
        cluster_dict=None,
        wait_for_ready=False,
        wait_timeout=TIMEOUT_30MIN,
        platform=None,
        gcp_service_account=None,
    ):
        """
        Provisions an OSD AWS cluster.

        Args:
            region (str, optional): The region where the cluster will be deployed. Defaults to None.
            ocp_version (str, optional): The OpenShift version for the cluster. Defaults to None.
            aws_access_key_id (str, optional): The AWS access key ID. Defaults to None.
            aws_account_id (str, optional): The AWS account ID. Defaults to None.
            aws_secret_access_key (str, optional): The AWS secret access key. Defaults to None.
            replicas (int, optional): The number of replicas for the cluster. Defaults to 2.
            compute_machine_type (str, optional): The type of compute machine for the cluster. Defaults to "m5.4xlarge".
            multi_az (bool, optional): Whether to use multiple availability zones. Defaults to False.
            channel_group (str, optional): The channel group for the cluster. Defaults to "stable".
            expiration_time (str, optional): The expiration time for the cluster. Defaults to None.
                Example: f"{(datetime.now() + timedelta(seconds=3600)).isoformat()}Z"
            cluster_dict (dict, optional): A dictionary with the configuration for an OSD AWS cluster. Defaults to None.
            wait_for_ready (bool, optional): Whether to wait for the cluster to be ready. Defaults to False.
            wait_timeout (int, optional): The timeout in seconds to wait for the cluster to be ready.
                Defaults to TIMEOUT_30MIN.
            platform (str): Target cluster platform. Supported: "aws" and "gpc"
            gcp_service_account (dict, optional): GCP service account dict. Defaults to None.

        Returns:
            object: The cluster object.

        Raises:
            ValueError: If any required attributes are missing.
        """
        if cluster_dict:
            _cluster_dict = cluster_dict
        else:
            frame = inspect.currentframe()
            frame_values = inspect.getargvalues(frame)[3]
            required_attributes = ["region", "ocp_version"]
            if platform == AWS_OSD_STR:
                required_attributes.extend([
                    "aws_access_key_id",
                    "aws_account_id",
                    "aws_secret_access_key",
                ])

            elif platform == GCP_OSD_STR:
                required_attributes.append("gcp_service_account")
            missing_attributes = [attr_name for attr_name in required_attributes if not frame_values.get(attr_name)]

            if missing_attributes:
                raise ValueError(f"Missing attributes: {missing_attributes}")

            _cluster_dict = self.osd_dict(
                region=region,
                ocp_version=ocp_version,
                aws_access_key_id=aws_access_key_id,
                aws_account_id=aws_account_id,
                aws_secret_access_key=aws_secret_access_key,
                replicas=replicas,
                compute_machine_type=compute_machine_type,
                multi_az=multi_az,
                channel_group=channel_group,
                expiration_time=expiration_time,
                platform=platform,
                gcp_service_account=gcp_service_account,
            )

        self.client.api_clusters_mgmt_v1_clusters_post(cluster=_cluster_dict)
        time_watcher = TimeoutWatch(timeout=wait_timeout)
        self.wait_exists(wait_timeout=wait_timeout)

        if wait_for_ready:
            self.wait_for_cluster_ready(wait_timeout=time_watcher.remaining_time())

        return self

    def wait_for_osd_cluster_ready_job(self, wait_timeout=TIMEOUT_60MIN):
        job = Job(
            client=self.ocp_client,
            name="osd-cluster-ready",
            namespace="openshift-monitoring",
        )
        job.wait_for_condition(
            condition=job.Condition.COMPLETE,
            status=job.Condition.Status.TRUE,
            timeout=wait_timeout,
        )


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
        return self.client.api_clusters_mgmt_v1_addons_addon_id_get(self.addon_name).to_dict()

    def get_addon_parameters_dict(self, addon_parameters):
        """Filter related addon parameters. Filter only related parameters if cluster condition(s) are set

        Args:
            addon_parameters (dict) : Addons parameters from Clusters Management
                cluster_mgmt_v1_addons_addon_id API.

        Returns:
            Dict of API addon parameters, including 'default_value' (if set), 'required' flag and 'value_type'

            Example:
                _addon_parameters = {
                    'cidr-range': {'default_value': '10.1.0.0/26', 'required': True, 'value_type': str},
                    'addon_parameter': {'default_value': '', 'required': False, 'value_type': bool},
                }
        """
        _addon_parameters_dict = {}

        for param in addon_parameters.get("items"):
            if param_conditions := [
                condition["data"] for condition in param.get("conditions", []) if condition["resource"] == "cluster"
            ]:
                if self.check_param_conditions(
                    cluster_dict=self.instance.to_dict(),
                    conditions_dict=param_conditions[0],
                ):
                    _addon_parameters_dict[param["id"]] = self._set_param_dict(_param=param)

            else:
                _addon_parameters_dict[param["id"]] = self._set_param_dict(_param=param)

        return _addon_parameters_dict

    def validate_and_update_addon_parameters(self, user_parameters=None, use_api_defaults=True):
        """
        Validate and update user input parameters against API's conditions and requirements.

        Args:
            user_parameters (list): User parameters, default is None.
                example: user_parameters = [
                    {"id": "has-external-resources", "value": "false"},
                    {"id": "aws-cluster-test-param", "value": "false"}
                ]
            use_api_defaults (bool): If true, set required parameter (which are not part of `user_parameters`) with
                default value to not fail as missing.

        Returns:
            list: Updated parameters (if default values updated) to provide for installation.

        Raises:
            ValueError: When a required parameter is missing,
                or when parameters are passed but not needed for addon.
        """

        _user_parameters = user_parameters or []
        addon_parameters = self.addon_info().get("parameters", {})
        user_addon_parameters = [param["id"] for param in _user_parameters]

        if not addon_parameters and _user_parameters:
            raise ValueError(f"{self.addon_name} does not take any parameters, got {user_addon_parameters}")

        addon_parameters_dict = self.get_addon_parameters_dict(addon_parameters=addon_parameters)
        _user_parameters = self.update_missing_params_from_defaults(
            _user_parameters=_user_parameters,
            addon_parameters_dict=addon_parameters_dict,
            use_api_defaults=use_api_defaults,
            user_addon_parameters=user_addon_parameters,
        )

        _user_parameters = self.update_param_value_type(
            _user_parameters=_user_parameters,
            addon_parameters_dict=addon_parameters_dict,
        )

        return _user_parameters

    @staticmethod
    def update_param_value_type(_user_parameters, addon_parameters_dict):
        for param in _user_parameters:
            param_type = addon_parameters_dict[param["id"]]["value_type"]
            param_value = param["value"]
            if not isinstance(param_value, param_type):
                param["value"] = param_type(param_value)  # noqa: FCN001

        return _user_parameters

    def update_missing_params_from_defaults(
        self,
        _user_parameters,
        addon_parameters_dict,
        use_api_defaults,
        user_addon_parameters,
    ):
        missing_parameter = []
        for param, param_dict in addon_parameters_dict.items():
            if param not in user_addon_parameters and param_dict["required"]:
                default_value = param_dict["default_value"]
                if use_api_defaults and default_value:
                    _user_parameters.append({
                        "id": param,
                        "value": default_value,
                    })
                else:
                    missing_parameter.append(param)
        if missing_parameter:
            raise ValueError(f"{self.addon_name} missing some required parameters {missing_parameter}")

        return _user_parameters

    def install_addon(
        self,
        parameters=None,
        wait=True,
        wait_timeout=TIMEOUT_30MIN,
        brew_token=None,
        rosa=False,
        use_api_defaults=True,
        must_gather_output_dir=None,
        kubeconfig_path=None,
    ):
        """
        Install addon on the cluster

        Args:
            parameters (list): List of dicts.
            wait (bool): True to wait for addon to be installed.
            wait_timeout (int): Timeout in seconds to wait for addon to be installed.
            brew_token (str): brew token for creating brew pull secret
            rosa (bool): Use ROSA cli if True else use OCM API
            use_api_defaults (bool): Use addon parameter default value if not provided.
            must_gather_output_dir (str, optional): Path to base directory where must-gather logs will be stored
            kubeconfig_path (str, optional): Path to kubeconfig

         Returns:
            AddOnInstallation or list: list of stdout responses if rosa is True, else AddOnInstallation
        """

        def _wait_for_rhoam_installation(_command):
            for rosa_sampler in self.addon_installation_instance_sampler(
                func=rosa_cli.execute,
                wait_timeout=TIMEOUT_5MIN,
                command=_command,
                ocm_client=self.client,
                aws_region=self.region,
            ):
                return rosa_sampler

        addon = AddOn(id=self.addon_name)
        _addon_installation_dict = {
            "id": self.addon_name,
            "addon": addon,
        }

        try:
            parameters = self.validate_and_update_addon_parameters(
                user_parameters=parameters, use_api_defaults=use_api_defaults
            )
            if self.addon_name == "managed-odh" and "stage" in self.client.api_client.configuration.host:
                self.create_rhods_brew_config(brew_token=brew_token)
            LOGGER.info(f"Installing addon {self.addon_name} v{self.addon_version}")
            if rosa:
                params_command = ""
                for parameter in parameters:
                    params_command += f" --{parameter['id']} {parameter['value']}"

                # TODO: remove support for billing-model flag once https://github.com/openshift/rosa/issues/1279 resolved
                command = (
                    f"install addon {self.addon_name} --cluster {self.name} {params_command} --billing-model standard"
                )

                if self.addon_name == "managed-api-service":
                    # TODO: remove _wait_for_rhoam_installation after https://github.com/openshift/rosa/issues/970 resolved
                    res = _wait_for_rhoam_installation(_command=command)
                else:
                    res = rosa_cli.execute(command=command, ocm_client=self.client, aws_region=self.region)
            else:
                if parameters:
                    _parameters = []
                    for params in parameters:
                        _parameters.append(AddOnInstallationParameter(id=params["id"], value=params["value"]))

                    _addon_installation_dict["parameters"] = {"items": _parameters}
                res = self.client.api_clusters_mgmt_v1_clusters_cluster_id_addons_post(
                    cluster_id=self.cluster_id,
                    add_on_installation=AddOnInstallation(_check_type=False, **_addon_installation_dict),
                )

            if self.addon_name == "managed-api-service" and "stage" in self.client.api_client.configuration.host:
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
                self.wait_for_install_state(state=self.State.READY, wait_timeout=wait_timeout)

            LOGGER.info(f"{self.addon_name} v{self.addon_version} successfully installed")
            return res

        except Exception as ex:
            LOGGER.error(f"{self.addon_name} Install Failed. \n{ex}")
            if must_gather_output_dir:
                collect_must_gather(
                    must_gather_output_dir=must_gather_output_dir,
                    kubeconfig_path=kubeconfig_path,
                    cluster_name=self.name,
                    product_name=self.addon_name,
                )
            raise

    def addon_installation_instance(self):
        try:
            return self.client.api_clusters_mgmt_v1_clusters_cluster_id_addons_addoninstallation_id_get(
                cluster_id=self.cluster_id, addoninstallation_id=self.addon_name
            )
        except NotFoundException:
            LOGGER.info(f"{self.addon_name} not found")
            return

    def wait_for_install_state(self, state, wait_timeout=TIMEOUT_30MIN):
        _state = None
        try:
            for _addon_installation_instance in self.addon_installation_instance_sampler(
                func=self.addon_installation_instance, wait_timeout=wait_timeout
            ):
                _state = str(_addon_installation_instance.get("state"))
                if _state == state:
                    return True
        except TimeoutExpiredError:
            LOGGER.error(f"Timeout waiting for {self.addon_name} state to be {state}, last state was {_state}")
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
                command=f"uninstall addon {self.addon_name} --cluster {self.name}",
                ocm_client=self.client,
                aws_region=self.region,
            )
        else:
            res = self.client.api_clusters_mgmt_v1_clusters_cluster_id_addons_addoninstallation_id_delete(
                cluster_id=self.cluster_id,
                addoninstallation_id=self.addon_name,
            )
        if wait:
            for _addon_installation_instance in self.addon_installation_instance_sampler(
                func=self.addon_installation_instance, wait_timeout=wait_timeout
            ):
                if not _addon_installation_instance:
                    return True
        LOGGER.info(f"{self.addon_name} v{self.addon_version} was successfully removed")
        return res

    def update_rhoam_cluster_storage_config(self):
        def _wait_for_rhmi_resource():
            for rhmi_sample in TimeoutSampler(
                wait_timeout=TIMEOUT_30MIN,
                sleep=SLEEP_1SEC,
                func=lambda: RHMI(
                    client=self.ocp_client,
                    name="rhoam",
                    namespace="redhat-rhoam-operator",
                ),
                exceptions_dict={
                    NotImplementedError: [],
                    **NOT_FOUND_ERROR_EXCEPTION_DICT,
                },
            ):
                if rhmi_sample and rhmi_sample.exists:
                    return rhmi_sample

        rhmi = _wait_for_rhmi_resource()
        ResourceEditor(patches={rhmi: {"spec": {"useClusterStorage": "false"}}}).update()
        rhmi.wait_for_stage_status_complete(timeout=TIMEOUT_45MIN)

    def create_rhods_brew_config(self, brew_token):
        icsp_name = "ocp-mgmt-wrapper-brew-registry"
        icsp = ImageContentSourcePolicy(
            client=self.ocp_client,
            name=icsp_name,
            repository_digest_mirrors=[
                {
                    "source": "registry.redhat.io/rhods",
                    "mirrors": ["brew.registry.redhat.io/rhods"],
                }
            ],
        )
        if icsp.exists:
            icsp.clean_up()
        icsp.deploy(wait=True)

        secret_data_dict = {"auths": {"brew.registry.redhat.io": {"auth": brew_token}}}
        create_update_secret(
            secret_data_dict=secret_data_dict,
            name="pull-secret",  # pragma: allowlist secret
            namespace="openshift-config",
            admin_client=self.ocp_client,
        )

    @staticmethod
    def check_param_conditions(cluster_dict, conditions_dict):
        """
        Check if parameter conditions met with cluster configuration

        Args:
            cluster_dict (dict): Cluster instance dict
            conditions_dict (dict): Parameter condition dict from API

        Returns:
            Bool: True if cluster instance match with conditions, else False

        """
        match_all = []
        for condition, condition_value in conditions_dict.items():
            cluster_condition_value = benedict(cluster_dict, keypath_separator=".").get(condition)

            match_all.append(
                isinstance(condition_value, list)
                and cluster_condition_value in condition_value
                or cluster_condition_value == condition_value
            )

        return all(match_all)

    @staticmethod
    def addon_installation_instance_sampler(func, wait_timeout=TIMEOUT_30MIN, **kwargs):
        return TimeoutSampler(wait_timeout=wait_timeout, sleep=SLEEP_1SEC, func=func, **kwargs)

    @staticmethod
    def _set_param_dict(_param):
        return {
            "required": _param.get("required"),
            "value_type": int if _param["value_type"] == "number" else str,
            "default_value": _param.get("default_value"),
        }
