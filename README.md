# openshift-cluster-management-python-wrapper
Wrapper for [openshift-cluster-management-python client](https://github.com/RedHatQE/openshift-cluster-management-python-client)

## Release new version
### requirements:
* Export GitHub token
```bash
export GITHUB_TOKEN=<your_github_token>
```
* [release-it](https://github.com/release-it/release-it)
```bash
sudo npm install --global release-it
npm install --save-dev @j-ulrich/release-it-regex-bumper
rm -f package.json package-lock.json
```
### usage:
* Create a release, run from the relevant branch.  
To create a 1.0 release, run:
```bash
git checkout v1.0
git pull
release-it # Follow the instructions
```

## Installation
From source:
```bash
git clone https://github.com/RedHatQE/openshift-cluster-management-python-client.git
cd openshift-cluster-management-python-client
python setup.py install --user
```

## Container
image locate at [openshift-cluster-management-python-wrapper](https://quay.io/repository/myakove/openshift-cluster-management-python-wrapper)
To pull the image: `podman pull quay.io/myakove/openshift-cluster-management-python-wrapper`

### Examples
# Usages

```
podman run quay.io/myakove/openshift-cluster-management-python-wrapper --help
podman run quay.io/myakove/openshift-cluster-management-python-wrapper install --help
podman run quay.io/myakove/openshift-cluster-management-python-wrapper uninstall --help
```

# Install Addon

```
podman run quay.io/myakove/openshift-cluster-management-python-wrapper \
    -t $OCM_TOKEN \
    -a ocm-addon-test-operator \
    -c cluster-name \
     install \
     -p has-external-resources=false \
     -p aws-cluster-test-param=false
```

# Uninstall Addon

```
podman run quay.io/myakove/openshift-cluster-management-python-wrapper \
    -t $OCM_TOKEN \
    -a ocm-addon-test-operator \
    -c cluster-name \
     uninstall
```

## Examples
### Client
```python
from ocm_python_wrapper.ocm_client import OCMPythonClient
ocm_client = OCMPythonClient(
    token=<ocm api token>>,
    endpoint=<endpoint url>,
    api_host=<production or stage>,
    discard_unknown_keys=True,
)
return ocm_client.client
```
### Cluster
```python
from ocm_python_wrapper.cluster import Cluster
cluster = Cluster(client=client, name=<cluster name>)
cluster_ocp_version = cluster.instance.version.raw_id
```
