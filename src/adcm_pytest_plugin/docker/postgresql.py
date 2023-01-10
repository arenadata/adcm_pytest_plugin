from docker.models.containers import Container


class PostgreSQL:
    def __init__(self, container: Container):
        self.container = container
