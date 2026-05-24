"""
1. Update the Traffic ad set to global audience (remove IL geo restriction)
2. Generate a before/after image with Kie.ai Nano Banana 2
3. Upload image to Meta, create new creative + ad

Run from project root:
    python3 -m scripts.new_painpoint_ad
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
from api.creative_manager import create_creative, upload_image
from api.campaign_manager import create_ad
from config.settings import META_AD_ACCOUNT_ID, KIE_AI_API_KEY

from facebook_business.adobjects.adset import AdSet
from facebook_business.exceptions import FacebookRequestError

# ── IDs ─────────────────────────────────────────────────────────────
TRAFFIC_ADSET_ID = "120245117061280200"
TRAFFIC_CAMPAIGN_ID = "120245117058950200"
LANDING_URL = "https://echoes-numerology.vercel.app/go"

# ── New global targeting ─────────────────────────────────────────────
GLOBAL_TARGETING = {
    "geo_locations": {
        # Top English-speaking + high-value spiritual app markets
        "countries": [
            "US", "GB", "CA", "AU", "NZ", "IE",   # English-speaking
            "IL",                                    # Israel (home market)
            "DE", "FR", "NL", "SE", "NO", "DK",    # Western Europe
            "BR", "MX", "AR",                        # Latin America
            "ZA",                                    # South Africa
        ]
    },
    "age_min": 25,
    "age_max": 55,
    "flexible_spec": [
        {
            "interests": [
                {"id": "6003840137852", "name": "Astrology"},
                {"id": "6002997573982", "name": "Horoscope"},
                {"id": "6003400407018", "name": "Self-help"},
                {"id": "6003224104145", "name": "Psychology"},
            ]
        }
    ],
    "targeting_automation": {
        "advantage_audience": 0,
    },
}

# ── New ad copy ───────────────────────────────────────────────────────
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

# ── Kie.ai image generation ───────────────────────────────────────────
IMAGE_PROMPT = (
    "A dramatic before/after split image for a numerology app ad. "
    "LEFT SIDE labeled 'BEFORE': A woman in her 30s looking confused and overwhelmed, "
    "surrounded by swirling dark toxic energy, broken heart symbols, chaotic relationships, "
    "moody dark purple and grey tones, exhausted expression. "
    "RIGHT SIDE labeled 'AFTER': The same woman looking radiant and confident, "
    "holding a phone showing glowing numerology numbers, surrounded by golden light and stars, "
    "calm and aligned, rich deep purple and gold tones. "
    "Bold text at the bottom: 'DISCOVER YOUR LIFE PATH'. "
    "Premium cinematic style, 9:16 vertical format, high contrast, mystical atmosphere."
)

KIE_BASE = "https://api.kie.ai/api/v1"
HEADERS = {
    "Authorization": f"Bearer {KIE_AI_API_KEY}",
    "Content-Type": "application/json",
}


def generate_image_kie() -> str:
    """Submit image generation task and poll until done. Returns image URL."""
    logger.info("Submitting Kie.ai image generation task...")
    resp = requests.post(
        f"{KIE_BASE}/jobs/createTask",
        headers=HEADERS,
        json={
            "model": "nano-banana-2",
            "input": {
                "prompt": IMAGE_PROMPT,
                "width": 1080,
                "height": 1920,
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    inner = data.get("data", data)
    task_id = (
        inner.get("taskId") or inner.get("task_id") or
        data.get("taskId") or data.get("task_id") or data.get("id")
    )
    if not task_id:
        raise ValueError(f"No task_id in response: {data}")
    logger.info("Task created: %s — polling for result...", task_id)

    # Poll up to 5 minutes
    for attempt in range(60):
        time.sleep(5)
        status_resp = requests.get(
            f"{KIE_BASE}/jobs/{task_id}",
            headers=HEADERS,
            timeout=15,
        )
        status_resp.raise_for_status()
        status_data = status_resp.json()
        job = status_data.get("data", status_data)
        state = (job.get("status") or job.get("state") or "").upper()
        logger.info("Attempt %d: status=%s", attempt + 1, state)

        if state in ("COMPLETED", "SUCCESS", "SUCCEEDED", "DONE", "FINISHED"):
            # Find image URL — check various response shapes
            output = job.get("output") or job.get("result") or {}
            if isinstance(output, dict):
                url = output.get("image_url") or output.get("url") or output.get("images", [None])[0]
            elif isinstance(output, list):
                url = output[0] if output else None
            else:
                url = str(output) if output else None

            if not url:
                # Try top-level
                url = job.get("image_url") or job.get("url")

            if url:
                logger.info("Image ready: %s", url[:80])
                return url
            raise ValueError(f"Job done but no image URL found: {job}")

        if state in ("FAILED", "ERROR", "CANCELLED"):
            raise RuntimeError(f"Kie.ai job {task_id} failed: {job}")

    raise TimeoutError(f"Kie.ai job {task_id} timed out after 5 minutes")


def download_image(url: str, suffix: str = ".jpg") -> str:
    """Download image to a temp file, return path."""
    logger.info("Downloading image from CDN...")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(r.content)
    tmp.close()
    logger.info("Saved to %s (%d KB)", tmp.name, len(r.content) // 1024)
    return tmp.name


def update_adset_global(adset_id: str):
    """Remove geo targeting so the ad set delivers worldwide."""
    logger.info("Updating ad set %s to global audience...", adset_id)
    client = MetaClient()
    adset = AdSet(adset_id)
    try:
        client.rate_limited_request(
            adset.api_update,
            params={"targeting": GLOBAL_TARGETING},
        )
        logger.info("Ad set updated to global targeting.")
    except FacebookRequestError as exc:
        logger.error("Failed to update targeting: [%s] %s", exc.api_error_code(), exc.api_error_message())
        raise


def main():
    logger.info("=== New Pain Point Ad: Toxic Relationships (Before/After) ===")

    # 1. Update ad set to global targeting
    update_adset_global(TRAFFIC_ADSET_ID)

    # 2. Generate before/after image with Kie.ai
    try:
        image_url = generate_image_kie()
        local_path = download_image(image_url, suffix=".jpg")
    except Exception as exc:
        logger.error("Image generation failed: %s", exc)
        logger.warning("Proceeding without new image — will use pain point hash as fallback")
        local_path = None

    # 3. Upload image to Meta
    if local_path:
        logger.info("Uploading image to Meta...")
        img_data = upload_image(local_path)
        image_hash = img_data["image_hash"]
        logger.info("Uploaded. Hash: %s", image_hash)
        os.unlink(local_path)
    else:
        # Fallback: reuse existing pain point image
        image_hash = "3aad7babe13d20e8ecbb2195a1860d61"
        logger.info("Using fallback image hash: %s", image_hash)

    # 4. Create creative
    logger.info("Creating creative...")
    creative = create_creative(
        name=AD_NAME,
        body=AD_BODY,
        title=AD_TITLE,
        link_url=LANDING_URL,
        image_hash=image_hash,
        call_to_action="LEARN_MORE",
        description=AD_DESCRIPTION,
    )
    creative_id = creative["id"]
    logger.info("Creative created: %s", creative_id)

    # 5. Create ad (ACTIVE)
    logger.info("Creating ad...")
    ad = create_ad(
        adset_id=TRAFFIC_ADSET_ID,
        name=AD_NAME,
        creative_id=creative_id,
        status="ACTIVE",
    )
    ad_id = ad["id"]
    logger.info("Ad created and active: %s", ad_id)

    print()
    print("=== DONE ===")
    print(f"Ad Set     : {TRAFFIC_ADSET_ID} (now GLOBAL)")
    print(f"Ad ID      : {ad_id}")
    print(f"Creative   : {creative_id}")
    print(f"Image hash : {image_hash}")
    print(f"URL        : {LANDING_URL}")


if __name__ == "__main__":
    main()
