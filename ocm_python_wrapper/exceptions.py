class AuthenticationFailed(Exception):
    pass


class EndpointAccessFailed(Exception):
    def __init__(self, err, endpoint):
        self.err = err
        self.endpoint = endpoint

    def __str__(self):
        return f"Failed to access {self.endpoint} endpoint.\nError Code: {self.err}"
