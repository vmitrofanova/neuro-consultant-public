import logging
import os

from app.database import Database
from app.jobs import Jobs
from app.queue import consume_sync
from app.supplier import SupplierClient, connect_supplier


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    jobs = Jobs(Database())
    jobs.initialize()
    with connect_supplier() as client:
        consume_sync(os.environ["RABBITMQ_URL"], jobs, SupplierClient(client))


if __name__ == "__main__":
    main()
