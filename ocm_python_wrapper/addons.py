from ocm_python_wrapper.exceptions import MissingResourceError


def get_addon_by_name(client, name):
    addon_list = client.api_clusters_mgmt_v1_addons_get()
    addon_info = [addon for addon in addon_list["items"] if addon.name == name]
    if addon_info:
        return addon_info[0]
    raise MissingResourceError(name=name, kind="addon")
