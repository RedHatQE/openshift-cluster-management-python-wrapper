FROM python

WORKDIR ocm-python-wrapper
COPY . .
RUN python -m pip install pip -U && python -m pip install .
ENTRYPOINT ["python", "scripts/cli.py", "--help"]
