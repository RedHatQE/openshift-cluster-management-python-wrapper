from ocm_python_wrapper.exceptions import MissingResourceError


def get_addons_list(api_client):
    return api_client.api_clusters_mgmt_v1_addons_get()


def get_addon_by_name(api_client, name):
    addon_list = get_addons_list(api_client=api_client)
    addon_info = [cluster for cluster in addon_list["items"] if cluster.name == name]
    if addon_info:
        return addon_info
    raise MissingResourceError(name=name, kind="addon")
