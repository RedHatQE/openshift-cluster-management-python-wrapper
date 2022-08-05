def get_cluster_id_by_name(client, cluster_name):
    cluster_info = client.api_clusters_mgmt_v1_clusters_get(search=f"name like '{cluster_name}%'")
    assert cluster_info.items, f"Cluster {cluster_name} does not exist"
    return cluster_info.items[0]["id"]


def get_cluster_config(client, cluster_name):
    cluster_id = get_cluster_id_by_name(client=client, cluster_name=cluster_name)
    return client.api_clusters_mgmt_v1_clusters_cluster_id_get(cluster_id=cluster_id)


def get_cluster_kubeconfig(client, cluster_id):
    cluster_credentials = client.api_clusters_mgmt_v1_clusters_cluster_id_credentials_get(cluster_id=cluster_id)
    return cluster_credentials._data_store["kubeconfig"]
