"""
Generate before/after image with Kie.ai, upload to Meta, update the toxic relationships ad.
Run from project root:
    python3 -m scripts.gen_and_update_image
"""

import logging
import os
import sys
import time
import requests
import tempfile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from api.meta_client import MetaClient
from api.creative_manager import upload_image, create_creative
from api.campaign_manager import create_ad
from config.settings import KIE_AI_API_KEY

# The ad and adset already created
TRAFFIC_ADSET_ID = "120245117061280200"
LANDING_URL = "https://echoes-numerology.vercel.app/go"
AD_NAME = "Echoes — Toxic Relationships (Before/After)"

AD_BODY = (
    "Do you keep attracting the same toxic relationships? "
    "The same dead-end patterns, over and over?\n\n"
    "It's not bad luck — it's your life path numbers pulling you off course.\n\n"
    "Echoes shows you the exact numerology cycles driving your relationships, "
    "your decisions, and your blind spots — so you can finally break the pattern.\n\n"
    "Free to try on the App Store."
)
AD_TITLE = "You Keep Attracting Toxic Relationships — Here's Why"
AD_DESCRIPTION = "See the hidden pattern. Change it. Start free."

IMAGE_PROMPT = (
    "Social media ad image, split in half vertically with a thin glowing divider. "
    "LEFT SIDE — 'BEFORE': A woman in her early 30s with dark circles under eyes, "
    "slouched posture, dark moody atmosphere, surrounded by faded broken heart icons "
    "and swirling dark energy, grey-purple cold tones, looking exhausted and lost. "
    "RIGHT SIDE — 'AFTER': The same woman standing tall, radiant smile, "
    "glowing warm light surrounding her, golden numerology symbols floating around her, "
    "holding a phone showing a numerology app with life path numbers, "
    "rich deep purple and gold warm tones, confident and aligned. "
    "Bold white text at the very bottom: 'DISCOVER YOUR LIFE PATH NUMBER'. "
    "Clean modern aesthetic, high contrast, cinematic quality, 4:5 aspect ratio."
)

KIE_BASE = "https://api.kie.ai/api/v1"
HEADERS = {
    "Authorization": f"Bearer {KIE_AI_API_KEY}",
    "Content-Type": "application/json",
}


def generate_image() -> str:
    logger.info("Submitting Kie.ai image generation task...")
    resp = requests.post(
        f"{KIE_BASE}/jobs/createTask",
        headers=HEADERS,
        json={
            "model": "nano-banana-2",
            "input": {
                "prompt": IMAGE_PROMPT,
                "width": 1080,
                "height": 1350,  # 4:5 ratio — optimal for Facebook/Instagram feed
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info("Kie.ai response: %s", data)

    inner = data.get("data", data)
    task_id = (
        inner.get("taskId") or inner.get("task_id") or
        data.get("taskId") or data.get("task_id") or data.get("id")
    )
    if not task_id:
        raise ValueError(f"No task_id in response: {data}")
    logger.info("Task ID: %s — polling...", task_id)

    import json as _json
    for attempt in range(72):  # up to 6 minutes
        time.sleep(5)
        r = requests.get(
            f"{KIE_BASE}/jobs/recordInfo",
            headers=HEADERS,
            params={"taskId": task_id},
            timeout=15,
        )
        r.raise_for_status()
        job = r.json().get("data", r.json())
        state = (job.get("state") or "").lower()
        logger.info("[%d] state=%s", attempt + 1, state)

        if state == "success":
            result_json = job.get("resultJson", "")
            try:
                result = _json.loads(result_json) if isinstance(result_json, str) else result_json
            except Exception:
                result = {}
            urls = result.get("resultUrls") or []
            url = urls[0] if urls else result.get("url") or result.get("image_url")
            if url:
                logger.info("Image URL: %s", url[:100])
                return url
            raise ValueError(f"Job done but no URL: {job}")

        if state in ("fail", "failed", "error"):
            raise RuntimeError(f"Job failed: {job}")

    raise TimeoutError("Timed out waiting for Kie.ai image")


def main():
    logger.info("=== Generate & Update Before/After Ad Image ===")

    # Generate image
    image_url = generate_image()

    # Download
    logger.info("Downloading image...")
    r = requests.get(image_url, timeout=60)
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    tmp.write(r.content)
    tmp.close()
    logger.info("Downloaded to %s (%d KB)", tmp.name, len(r.content) // 1024)

    # Upload to Meta
    logger.info("Uploading to Meta...")
    img_data = upload_image(tmp.name)
    image_hash = img_data["image_hash"]
    os.unlink(tmp.name)
    logger.info("Meta image hash: %s", image_hash)

    # Create new creative with the actual before/after image
    logger.info("Creating creative with new image...")
    creative = create_creative(
        name=f"{AD_NAME} v2",
        body=AD_BODY,
        title=AD_TITLE,
        link_url=LANDING_URL,
        image_hash=image_hash,
        call_to_action="LEARN_MORE",
        description=AD_DESCRIPTION,
    )
    creative_id = creative["id"]
    logger.info("Creative: %s", creative_id)

    # Create new ad with this creative
    logger.info("Creating ad...")
    ad = create_ad(
        adset_id=TRAFFIC_ADSET_ID,
        name=f"{AD_NAME} v2",
        creative_id=creative_id,
        status="ACTIVE",
    )
    ad_id = ad["id"]

    print()
    print("=== DONE ===")
    print(f"Image hash : {image_hash}")
    print(f"Creative   : {creative_id}")
    print(f"Ad ID      : {ad_id}  (ACTIVE)")


if __name__ == "__main__":
    main()
