#! /usr/bin/python
# -*- coding: utf-8 -*-

from setuptools import find_packages, setup


ocm_python_client = "/home/rnetser/git/openshift-cluster-management-python-client-upstream"

setup(
    name="openshift-cluster-management-python-wrapper",
    license="apache-2.0",
    keywords=["Openshift", "OCM"],
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "colorlog",
        #"ocm-python-client",
        f"ocm_python_client @ file://localhost/{ocm_python_client}#egg=ocm_python_client",
        "requests",
    ],
    python_requires=">=3.6",
)
