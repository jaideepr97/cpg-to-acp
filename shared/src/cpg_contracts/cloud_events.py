"""CloudEvent helper for SonataFlow async callbacks.

Services that run LLM work asynchronously use this to POST a CloudEvent
back to the SonataFlow callback URL when the work is done. The
kogitoprocrefid extension correlates the event to the waiting workflow
instance.
"""

import json
import logging
from uuid import uuid4

import requests

logger = logging.getLogger(__name__)


def post_callback(
    callback_url: str,
    process_instance_id: str,
    event_type: str,
    data: dict,
) -> bool:
    """POST a CloudEvent to the SonataFlow callback URL.

    Returns True if the callback was delivered successfully.
    """
    cloud_event = {
        "specversion": "1.0",
        "id": str(uuid4()),
        "source": "",
        "type": event_type,
        "kogitoprocrefid": process_instance_id,
        "datacontenttype": "application/json",
        "data": data,
    }
    try:
        r = requests.post(
            callback_url,
            json=cloud_event,
            headers={"Content-Type": "application/cloudevents+json"},
            timeout=30,
        )
        r.raise_for_status()
        logger.info(
            "Callback delivered: type=%s instance=%s url=%s",
            event_type, process_instance_id, callback_url,
        )
        return True
    except Exception as e:
        logger.error(
            "Callback failed: type=%s instance=%s url=%s error=%s",
            event_type, process_instance_id, callback_url, e,
        )
        return False
