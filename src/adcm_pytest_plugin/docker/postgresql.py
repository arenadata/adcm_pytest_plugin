from docker.models.containers import Container


class PostgreSQL:  # pylint: disable=too-few-public-methods
    def __init__(self, container: Container):
        self.container = container
