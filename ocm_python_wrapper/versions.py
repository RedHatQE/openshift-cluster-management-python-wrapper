from collections import defaultdict


class Versions:
    def __init__(self, client):
        self.client = client

    def get(self, version_prefix=None, channel_group=None, size=10000):
        version_kwargs = {"order": "id desc", "size": size}
        version_search_str = "enabled = 't'"
        if channel_group:
            version_search_str += f"and channel_group = '{channel_group}'"
        if version_prefix:
            version_search_str += f"and raw_id like '{version_prefix}%'"
        version_kwargs["search"] = version_search_str
        versions_list = self.client.api_clusters_mgmt_v1_versions_get(**version_kwargs)

        base_available_versions_dict = defaultdict(list)
        for version in versions_list.items:
            base_available_versions_dict.setdefault(version.channel_group, []).append(
                version.raw_id
            )

        return base_available_versions_dict
