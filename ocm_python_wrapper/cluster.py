class Cluster:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.cluster_id = self._id()

    def _id(self):
        cluster_info = self.client.api_clusters_mgmt_v1_clusters_get(search=f"name like '{self.name}%'")
        assert cluster_info.items, f"Cluster {self.name} does not exist"
        return cluster_info.items[0]["id"]

    def credentials(self):
        return self.client.api_clusters_mgmt_v1_clusters_cluster_id_credentials_get(cluster_id=self.cluster_id)._data_store

    def kubeconfig(self):
        return self.credentials()["kubeconfig"]

    def addons(self):
        pass
