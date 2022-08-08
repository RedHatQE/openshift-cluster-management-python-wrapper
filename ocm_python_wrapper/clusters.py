from ocm_python_wrapper.exceptions import MissingResourceError


def get_cluster_list(api_client):
    return api_client.api_clusters_mgmt_v1_clusters_get()


def get_cluster_by_name(api_client, name):
    cluster_list = get_cluster_list(api_client=api_client)
    cluster_info = [cluster for cluster in cluster_list["items"] if cluster.name == name]
    if cluster_info:
        return cluster_info[0]
    raise MissingResourceError(name=name, kind="cluster")
