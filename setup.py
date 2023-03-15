#! /usr/bin/python
# -*- coding: utf-8 -*-

from setuptools import find_packages, setup

setup(
    name="openshift-cluster-management-python-wrapper",
    license="apache-2.0",
    keywords=["Openshift", "OCM"],
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "colorlog",
        "ocm-python-client",
        "openshift-python-wrapper",
        "requests",
        "pyyaml",
        "openshift-python-utilities",
    ],
    python_requires=">=3.6",
)
