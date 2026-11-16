import logging
from uuid import UUID, uuid4

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pydantic import BaseModel, ValidationError

from app.catalog import Catalog
from app.infrastructure import connect_rabbitmq
from app.supplier import SupplierClient, SupplierError

QUEUE = "catalog.sync"
FAILED_QUEUE = "catalog.sync.failed"
logger = logging.getLogger(__name__)


class SyncJob(BaseModel):
    task_id: UUID


def declare_queues(channel: BlockingChannel) -> None:
    channel.queue_declare(queue=FAILED_QUEUE, durable=True)
    channel.queue_declare(
        queue=QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": FAILED_QUEUE,
        },
    )


def enqueue_sync(url: str) -> SyncJob:
    job = SyncJob(task_id=uuid4())
    with connect_rabbitmq(url) as connection:
        channel = connection.channel()
        declare_queues(channel)
        channel.confirm_delivery()
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE,
            body=job.model_dump_json().encode(),
            properties=pika.BasicProperties(
                content_type="application/json", delivery_mode=2, type="catalog.sync"
            ),
            mandatory=True,
        )
    return job


def consume_sync(url: str, catalog: Catalog, supplier: SupplierClient) -> None:
    with connect_rabbitmq(url) as connection:
        channel = connection.channel()
        declare_queues(channel)
        channel.basic_qos(prefetch_count=1)
        for delivery, _, body in channel.consume(QUEUE):
            try:
                job = SyncJob.model_validate_json(body)
                catalog.upsert(supplier.fetch_products())
            except (SupplierError, ValidationError) as exc:
                logger.warning("Sync job rejected: %s", type(exc).__name__)
                channel.basic_nack(delivery.delivery_tag, requeue=False)
            else:
                channel.basic_ack(delivery.delivery_tag)
                logger.info("Sync job completed: %s", job.task_id)
