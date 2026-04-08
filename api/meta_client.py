"""
Core Meta Marketing API client wrapper.

Handles initialization, authentication, rate limiting, pagination,
and provides the shared AdAccount object used by all other API modules.
"""

import logging
import time
from typing import Any

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.exceptions import FacebookRequestError

from config.settings import (
    META_APP_ID,
    META_APP_SECRET,
    META_ACCESS_TOKEN,
    META_AD_ACCOUNT_ID,
)

logger = logging.getLogger(__name__)

# Rate-limit defaults
_DEFAULT_MAX_RETRIES = 5
_DEFAULT_BASE_DELAY = 2.0  # seconds
_DEFAULT_MAX_DELAY = 120.0  # seconds


class MetaClient:
    """Singleton-style wrapper around the Facebook Marketing API.

    Usage::

        client = MetaClient()
        account = client.get_account()
    """

    _instance: "MetaClient | None" = None

    def __new__(cls) -> "MetaClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._init_api()
        self._initialized = True

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_api(self) -> None:
        """Initialize the Facebook Ads API with credentials from settings."""
        if not META_ACCESS_TOKEN:
            raise ValueError(
                "META_ACCESS_TOKEN is not set. "
                "Add it to your .env file or config/settings.py."
            )
        if not META_AD_ACCOUNT_ID:
            raise ValueError(
                "META_AD_ACCOUNT_ID is not set. "
                "It should look like 'act_123456789'."
            )

        self._api = FacebookAdsApi.init(
            app_id=META_APP_ID,
            app_secret=META_APP_SECRET,
            access_token=META_ACCESS_TOKEN,
            api_version="v21.0",
        )
        self._account = AdAccount(META_AD_ACCOUNT_ID)
        logger.info(
            "Meta API initialised for account %s (API v21.0)", META_AD_ACCOUNT_ID
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_account(self) -> AdAccount:
        """Return the AdAccount object for the configured account."""
        return self._account

    def get_account_id(self) -> str:
        """Return the raw ad-account ID string (e.g. ``act_123456``)."""
        return META_AD_ACCOUNT_ID

    # ------------------------------------------------------------------
    # Rate-limit / retry helper
    # ------------------------------------------------------------------

    @staticmethod
    def rate_limited_request(
        callable_fn: Any,
        *args: Any,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_delay: float = _DEFAULT_BASE_DELAY,
        max_delay: float = _DEFAULT_MAX_DELAY,
        **kwargs: Any,
    ) -> Any:
        """Execute *callable_fn* with exponential-backoff retry on rate limits.

        Meta returns HTTP 429 or error code 17 / 32 when the rate limit is
        hit.  This helper sleeps and retries with exponential backoff.

        Parameters
        ----------
        callable_fn:
            Any callable that talks to the Meta API.
        max_retries:
            Maximum number of retry attempts before raising.
        base_delay:
            Initial delay in seconds (doubled on each retry).
        max_delay:
            Cap for the delay between retries.

        Returns
        -------
        The return value of *callable_fn*.
        """
        last_exception: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return callable_fn(*args, **kwargs)
            except FacebookRequestError as exc:
                last_exception = exc
                error_code = exc.api_error_code()

                # Rate-limit codes: 17 = user request limit, 32 = API call limit,
                # 4 = app-level throttling, 80004 = insights throttling
                rate_limit_codes = {4, 17, 32, 80004}

                if error_code not in rate_limit_codes:
                    # Not a rate-limit error — propagate immediately
                    logger.error(
                        "Meta API error (code=%s, subcode=%s): %s",
                        error_code,
                        exc.api_error_subcode(),
                        exc.api_error_message(),
                    )
                    raise

                if attempt == max_retries:
                    logger.error(
                        "Rate limit still hit after %d retries — giving up.",
                        max_retries,
                    )
                    raise

                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    "Rate limited (code=%s). Retry %d/%d in %.1fs …",
                    error_code,
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)

        # Should be unreachable, but satisfy the type checker.
        raise last_exception  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Pagination helper
    # ------------------------------------------------------------------

    @staticmethod
    def exhaust_pagination(cursor: Any) -> list[dict[str, Any]]:
        """Consume a Facebook API ``Cursor`` and return a flat list of dicts.

        The SDK returns lazy ``Cursor`` objects that page through results.
        This helper iterates the full set and exports each object to a plain
        dict so downstream code never has to touch SDK objects directly.

        Parameters
        ----------
        cursor:
            A ``facebook_business.api.Cursor`` (returned by most
            ``get_*`` calls on AdAccount / Campaign / etc.).

        Returns
        -------
        list[dict]
            Every record, fully materialised.
        """
        results: list[dict[str, Any]] = []
        for item in cursor:
            results.append(dict(item))
        return results

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Test the API connection and return account metadata.

        Returns
        -------
        dict
            Keys: ``ok`` (bool), ``account_id``, ``account_name``,
            ``currency``, ``timezone``, and ``error`` (if any).
        """
        try:
            info = self.rate_limited_request(
                self._account.api_get,
                fields=[
                    "name",
                    "account_status",
                    "currency",
                    "timezone_name",
                    "amount_spent",
                    "balance",
                ],
            )
            status_map = {
                1: "ACTIVE",
                2: "DISABLED",
                3: "UNSETTLED",
                7: "PENDING_RISK_REVIEW",
                8: "PENDING_SETTLEMENT",
                9: "IN_GRACE_PERIOD",
                100: "PENDING_CLOSURE",
                101: "CLOSED",
                201: "ANY_ACTIVE",
                202: "ANY_CLOSED",
            }
            raw_status = info.get("account_status", 0)
            return {
                "ok": True,
                "account_id": info.get("id", META_AD_ACCOUNT_ID),
                "account_name": info.get("name", ""),
                "account_status": status_map.get(raw_status, f"UNKNOWN({raw_status})"),
                "currency": info.get("currency", ""),
                "timezone": info.get("timezone_name", ""),
                "amount_spent": info.get("amount_spent", "0"),
                "balance": info.get("balance", "0"),
            }
        except FacebookRequestError as exc:
            logger.error("Health check failed: %s", exc.api_error_message())
            return {
                "ok": False,
                "account_id": META_AD_ACCOUNT_ID,
                "error": exc.api_error_message(),
                "error_code": exc.api_error_code(),
            }
        except Exception as exc:
            logger.exception("Unexpected error during health check")
            return {
                "ok": False,
                "account_id": META_AD_ACCOUNT_ID,
                "error": str(exc),
            }
