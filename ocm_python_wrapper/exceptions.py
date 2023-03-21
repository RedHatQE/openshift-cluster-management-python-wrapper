class AuthenticationError(Exception):
    pass


class EndpointAccessError(Exception):
    def __init__(self, err, endpoint):
        self.err = err
        self.endpoint = endpoint

    def __str__(self):
        return f"Failed to access {self.endpoint} endpoint.\nError Code: {self.err}"


class MissingResourceError(Exception):
    def __init__(self, name, kind):
        self.kind = kind
        self.name = name

    def __str__(self):
        return f"{self.kind} named {self.name} was not found."


class ClusterInstallError(Exception):
    pass
