import os
import logging
from pathlib import Path

import boto3

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.getenv("MAILAI_STATE_S3_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def _bucket() -> str:
    return (os.getenv("MAILAI_STATE_S3_BUCKET") or os.getenv("S3_BUCKET") or "").strip()


def _endpoint_url() -> str | None:
    v = (os.getenv("MAILAI_STATE_S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT_URL") or "").strip()
    return v or None


def _region() -> str:
    return (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "auto").strip()


def _client():
    return boto3.client("s3", endpoint_url=_endpoint_url(), region_name=_region())


def _key_for(path: Path) -> str:
    prefix = (os.getenv("MAILAI_STATE_S3_PREFIX") or "mailai").strip().strip("/")
    return f"{prefix}/{path.as_posix()}"


def try_restore_file(local_path: Path) -> bool:
    """
    If enabled and bucket configured, download the object for local_path
    into local_path when missing. Returns True if restored.
    """
    if not _enabled():
        return False
    if local_path.exists():
        return False
    bucket = _bucket()
    if not bucket:
        logger.warning("MAILAI_STATE_S3_ENABLED=true but no bucket configured.")
        return False

    key = _key_for(local_path)
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        _client().download_file(bucket, key, str(local_path))
        logger.info(f"Restored {local_path} from s3://{bucket}/{key}")
        return True
    except Exception as e:
        logger.warning(
            f"Could not restore {local_path} from s3://{bucket}/{key}: {e}. "
            "Check MAILAI_STATE_S3_* settings and bucket read permissions."
        )
        return False


def try_persist_file(local_path: Path) -> bool:
    """
    If enabled and bucket configured, upload local_path to S3.
    Returns True if uploaded.
    """
    if not _enabled():
        return False
    if not local_path.exists():
        return False
    bucket = _bucket()
    if not bucket:
        logger.warning("MAILAI_STATE_S3_ENABLED=true but no bucket configured.")
        return False

    key = _key_for(local_path)
    try:
        _client().upload_file(str(local_path), bucket, key)
        logger.info(f"Persisted {local_path} to s3://{bucket}/{key}")
        return True
    except Exception as e:
        logger.warning(
            f"Could not persist {local_path} to s3://{bucket}/{key}: {e}. "
            "Check MAILAI_STATE_S3_* settings and bucket write permissions."
        )
        return False
