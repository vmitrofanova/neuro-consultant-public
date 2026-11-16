import logging
import os

from app.catalog import create_catalog
from app.queue import consume_sync
from app.supplier import SupplierClient, connect_supplier


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    catalog = create_catalog()
    catalog.initialize()
    with connect_supplier() as client:
        consume_sync(os.environ["RABBITMQ_URL"], catalog, SupplierClient(client))


if __name__ == "__main__":
    main()
