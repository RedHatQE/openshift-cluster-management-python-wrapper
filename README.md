# openshift-cluster-management-python-wrapper
Wrapper for [openshift-cluster-management-python client](https://github.com/RedHatQE/openshift-cluster-management-python-client)

## Release new version
### requirements:
* Export GitHub token
```bash
export GITHUB_TOKEN=<your_github_token>
```
* [release-it](https://github.com/release-it/release-it)

Run the following once (execute outside repository dir, for example `~/`):
```bash
sudo npm install --global release-it
npm install --save-dev @release-it/bumper
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
