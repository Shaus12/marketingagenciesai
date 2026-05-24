"""
Launch a new OUTCOME_TRAFFIC campaign pointing to echoes-numerology.vercel.app/go

This replaces the OUTCOME_APP_PROMOTION approach for ad creatives.
The /go page fires a Meta Pixel ViewContent event then redirects to the App Store.
Run from the project root:
    python3 -m scripts.launch_traffic_campaign
"""

import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from api.meta_client import MetaClient
from api.campaign_manager import create_campaign, create_adset, create_ad
from api.creative_manager import create_creative, get_creative_details
from config.settings import META_AD_ACCOUNT_ID

from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.ad import Ad
from facebook_business.exceptions import FacebookRequestError

LANDING_URL = "https://echoes-numerology.vercel.app/go"

# Interest IDs: Women 28-50 in IL interested in astrology/numerology/spirituality
TARGETING = {
    "geo_locations": {"countries": ["IL"]},
    "age_min": 28,
    "age_max": 50,
    "genders": [2],  # 2 = female
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
        "advantage_audience": 0,  # 0 = manual targeting, 1 = Advantage+
    },
}

# Image hashes from account's uploaded images (fetched from adimages endpoint)
IMAGE_HASHES = {
    "hook_text": "33713c4676999deaf13cf3f4a90fcbe3",
    "pain_point": "3aad7babe13d20e8ecbb2195a1860d61",
}

# Ad copy
ADS = [
    {
        "key": "hook_text",
        "creative_name": "Echoes — Hook Text (Traffic)",
        "title": "Your Numbers Know The Truth",
        "body": (
            "Most apps give you horoscopes. Echoes gives you your life's hidden pattern.\n\n"
            "Enter your birth date and see the numbers guiding every decision you make — "
            "your path, your cycles, your destiny.\n\n"
            "Free to try on the App Store."
        ),
        "cta": "LEARN_MORE",
        "description": "Numerology insights built for modern women",
    },
    {
        "key": "pain_point",
        "creative_name": "Echoes — Pain Point (Traffic)",
        "title": "Why Does Everything Feel Off Right Now?",
        "body": (
            "When life feels stuck, chaotic, or like nothing is working — "
            "there's often a deeper pattern at play.\n\n"
            "Echoes reveals the numerology cycles shaping your current season of life. "
            "Understand what's happening — and what's coming next.\n\n"
            "Free to try on the App Store."
        ),
        "cta": "LEARN_MORE",
        "description": "Understand your cycles. Trust the timing.",
    },
]


def get_image_hash_from_creative(creative_id: str):
    """Fetch the image hash from an existing creative."""
    from facebook_business.adobjects.adcreative import AdCreative
    client = MetaClient()
    creative = AdCreative(creative_id)
    try:
        # Only request fields that exist for app-promotion creatives
        info = client.rate_limited_request(
            creative.api_get,
            fields=["id", "name", "image_hash", "object_story_spec", "thumbnail_url"],
        )
        data = dict(info)
        # image_hash may be top-level or nested
        if data.get("image_hash"):
            return data["image_hash"]
        spec = data.get("object_story_spec", {})
        link_data = spec.get("link_data", {})
        if link_data.get("image_hash"):
            return link_data["image_hash"]
        # For APP_PROMOTION creatives, image might be in a different path
        object_data = spec.get("object_data", {}) or spec.get("app_data", {})
        if object_data.get("image_hash"):
            return object_data["image_hash"]
        logger.warning("No image hash found in creative %s. Data: %s", creative_id, data)
        return None
    except Exception as exc:
        logger.error("Failed to get creative %s: %s", creative_id, exc)
        return None


def main():
    logger.info("=== Echoes Traffic Campaign Launch ===")

    client = MetaClient()
    account = client.get_account()

    # Campaign and ad set already created — reuse them
    campaign_id = "120245117058950200"
    adset_id = "120245117061280200"
    logger.info("Using existing campaign %s, ad set %s", campaign_id, adset_id)

    # Step 3: Create creatives + ads using known image hashes
    created = []
    for ad_spec in ADS:
        key = ad_spec["key"]
        image_hash = IMAGE_HASHES[key]

        logger.info("Creating traffic creative for %s (image_hash=%s)...", key, image_hash)
        creative = create_creative(
            name=ad_spec["creative_name"],
            body=ad_spec["body"],
            title=ad_spec["title"],
            link_url=LANDING_URL,
            image_hash=image_hash,
            call_to_action=ad_spec["cta"],
            description=ad_spec["description"],
        )
        creative_id = creative["id"]
        logger.info("Creative created: %s", creative_id)

        logger.info("Creating ad for %s...", key)
        ad = create_ad(
            adset_id=adset_id,
            name=ad_spec["creative_name"],
            creative_id=creative_id,
            status="ACTIVE",
        )
        ad_id = ad["id"]
        logger.info("Ad created: %s", ad_id)

        created.append({
            "key": key,
            "creative_id": creative_id,
            "ad_id": ad_id,
        })

    # Step 4: Activate ad set and campaign
    logger.info("Activating ad set %s...", adset_id)
    from facebook_business.adobjects.adset import AdSet
    from facebook_business.adobjects.campaign import Campaign

    client = MetaClient()
    adset_obj = AdSet(adset_id)
    client.rate_limited_request(adset_obj.api_update, params={"status": "ACTIVE"})

    campaign_obj = Campaign(campaign_id)
    client.rate_limited_request(campaign_obj.api_update, params={"status": "ACTIVE"})
    logger.info("Campaign %s activated.", campaign_id)

    # Summary
    print("\n=== LAUNCH COMPLETE ===")
    print(f"Campaign ID : {campaign_id}")
    print(f"Ad Set ID   : {adset_id}")
    print(f"Landing URL : {LANDING_URL}")
    print(f"Budget      : ₪20/day")
    print()
    for item in created:
        print(f"[{item['key']}]")
        print(f"  Creative ID : {item['creative_id']}")
        print(f"  Ad ID       : {item['ad_id']}")
    print()
    print("Both ads are ACTIVE. Traffic → /go → App Store with Pixel tracking.")
    print("Keep the APP_PROMOTION campaign PAUSED until Meta SDK sends events.")


if __name__ == "__main__":
    main()
