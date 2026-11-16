import logging

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pydantic import ValidationError

from app.infrastructure import connect_rabbitmq
from app.jobs import Jobs, SyncJob
from app.supplier import SupplierClient, SupplierError, SupplierTimeout

QUEUE = "catalog.sync"
FAILED_QUEUE = "catalog.sync.failed"
logger = logging.getLogger(__name__)


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


def publish_sync(url: str, job: SyncJob) -> None:
    with connect_rabbitmq(url) as connection:
        channel = connection.channel()
        declare_queues(channel)
        channel.confirm_delivery()
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE,
            body=job.model_dump_json().encode(),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                message_id=str(job.task_id),
                type="catalog.sync",
            ),
            mandatory=True,
        )


def consume_sync(url: str, jobs: Jobs, supplier: SupplierClient) -> None:
    with connect_rabbitmq(url) as connection:
        channel = connection.channel()
        declare_queues(channel)
        channel.basic_qos(prefetch_count=1)
        for delivery, properties, body in channel.consume(QUEUE):
            tag = delivery.delivery_tag
            try:
                job = SyncJob.model_validate_json(body)
            except ValidationError:
                logger.warning("Invalid sync job payload")
                channel.basic_nack(tag, requeue=False)
                continue

            status = jobs.start(job.task_id, legacy=properties.message_id is None)
            if status == "succeeded":
                channel.basic_ack(tag)
                continue
            if status != "running":
                channel.basic_nack(tag, requeue=False)
                continue

            try:
                products = supplier.fetch_products()
            except SupplierError as exc:
                error = (
                    "supplier_timeout"
                    if isinstance(exc, SupplierTimeout)
                    else "supplier_error"
                )
                if jobs.fail(job.task_id, error):
                    channel.basic_nack(tag, requeue=False)
                    logger.warning("Sync job failed: %s (%s)", job.task_id, error)
                else:
                    channel.basic_ack(tag)
            else:
                if jobs.succeed(job.task_id, products):
                    logger.info("Sync job completed: %s", job.task_id)
                channel.basic_ack(tag)
