"""Lambda entry point for the mail bucket: an S3 notification for each email SES stored."""

import logging
import os
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import boto3

from jobmecloud.config import paths
from jobmecloud.db.engine import make_engine
from jobmecloud.inbound.service import handle_email
from jobmecloud.inbound.trust import TrustConfig
from jobmecloud.jobs.dispatch import LambdaDispatcher
from jobmecloud.llm.redact import install_log_redaction

log = logging.getLogger(__name__)
DEFAULT_DAILY_LIMIT = 5


def handler(event: dict, context) -> None:
    install_log_redaction()
    data_dir = paths.data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(data_dir=data_dir)
    config = TrustConfig(address=os.environ["JOBMECLOUD_INBOUND_ADDRESS"], sender=os.environ["JOBMECLOUD_INBOUND_SENDER"])
    limit = int(os.environ.get("JOBMECLOUD_INBOUND_DAILY_LIMIT", DEFAULT_DAILY_LIMIT))
    s3, dispatcher = boto3.client("s3"), LambdaDispatcher()
    failures: list[Exception] = []
    try:
        for record in event.get("Records", []):
            bucket, key = record["s3"]["bucket"]["name"], unquote_plus(record["s3"]["object"]["key"])
            try:
                status = handle_email(engine, s3, dispatcher, bucket=bucket, key=key, config=config,
                                      daily_limit=limit, now=datetime.now(timezone.utc))
                log.info("Inbound email %s: %s", key, status)
            except Exception as e:
                log.exception("Inbound email %s failed", key)
                failures.append(e)
    finally:
        engine.dispose()
    if failures:
        raise failures[0]  # Lambda retries the notification; an email still marked received is picked up again
