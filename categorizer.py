"""
Merchant categorizer backed by MCC (Merchant Category Code) groupings.

Since bank alert emails contain merchant *names* (not MCC codes), we maintain
a name → MCC mapping for known SG merchants, then resolve MCC → category.
RapidFuzz fuzzy-matches incoming names against the known list.

MCC references:
  5411        Grocery Stores, Supermarkets
  5412        Convenience Stores
  5499        Misc Food Stores
  5812        Eating Places, Restaurants
  5814        Fast Food Restaurants
  5411..5499  Broad food retail band
  4111        Local/Suburban Commuter Transport
  4121        Taxicabs and Limousines
  4131        Bus Lines
  5912        Drug Stores and Pharmacies
  5999        Misc Retail Stores
  7011        Hotels and Motels
  5941        Sporting Goods
  5945        Hobby, Toy and Game Shops
  5200        Home Supply Warehouse
  5999        General Retail
"""

import logging
import time
from rapidfuzz import process
import anthropic
import config

logger = logging.getLogger(__name__)

# MCC → simplified category
MCC_CATEGORY: dict[int, str] = {
    5411: "FAMILY",
    5412: "FAMILY",
    5499: "DINING",    # Misc Food Stores — counts as dining per UOB Lady benefit rules
    5641: "FAMILY",    # Children's/infants' wear stores
    5812: "DINING",
    5814: "DINING",
    5811: "DINING",
    4111: "TRANSPORT",
    4121: "TRANSPORT",
    4131: "TRANSPORT",
    5912: "HEALTH",
    7011: "TRAVEL",
    5941: "SHOPPING",
    5945: "SHOPPING",
    5200: "SHOPPING",
    5999: "OTHER",
}

# Merchant name (uppercase) → MCC code
# Focused on common SG merchants; extend as transactions arrive.
MERCHANT_MCC: dict[str, int] = {
    # Groceries — MCC 5411
    "NTUC FAIRPRICE": 5411,
    "NTUC": 5411,
    "FAIRPRICE": 5411,
    "GIANT": 5411,
    "COLD STORAGE": 5411,
    "SHENG SIONG": 5411,
    "PRIME SUPERMARKET": 5411,
    "MARKETS PLACE": 5411,
    "JASON S DELI": 5411,
    "LITTLE FARMS": 5411,
    "MUSTAFA SUPERMARKET": 5411,
    # Convenience — MCC 5412
    "7-ELEVEN": 5412,
    "CHEERS": 5412,
    # Dining — MCC 5812
    "GRAB FOOD": 5812,
    "FOODPANDA": 5812,
    "DELIVEROO": 5812,
    "KOUFU": 5812,
    "KOPITIAM": 5812,
    "FOOD REPUBLIC": 5812,
    "HAWKER": 5812,
    "SELECTED FOODS": 5812,
    "SOUP RESTAURANT": 5812,
    "PARADISE": 5812,
    "DIN TAI FUNG": 5812,
    "CRYSTAL JADE": 5812,
    "OLD CHANG KEE": 5812,
    "BENGAWAN SOLO": 5812,
    "YA KUN": 5812,
    "TOAST BOX": 5812,
    "STARBUCKS": 5812,
    "COSTA COFFEE": 5812,
    "THE COFFEE BEAN": 5812,
    # Fast food — MCC 5814
    "MCD": 5814,
    "MCDONALD": 5814,
    "KFC": 5814,
    "BURGER KING": 5814,
    "SUBWAY": 5814,
    "PIZZA HUT": 5814,
    "DOMINO": 5814,
    "POPEYES": 5814,
    "JOLLIBEE": 5814,
    "TEXAS CHICKEN": 5814,
    "LONG JOHN SILVER": 5814,
    # Transport — MCC 4111 / 4121
    "GRAB": 4121,
    "GOJEK": 4121,
    "TADA": 4121,
    "RYDE": 4121,
    "COMFORT TAXI": 4121,
    "COMFORTDELGRO": 4121,
    "SBS TRANSIT": 4111,
    "SMRT": 4111,
    "EZ-LINK": 4111,
    "TRANSITLINK": 4111,
    # Health — MCC 5912
    "GUARDIAN": 5912,
    "WATSONS": 5912,
    "UNITY PHARMACY": 5912,
    "ALPHA PHARMACY": 5912,
    # Travel — MCC 7011
    "AGODA": 7011,
    "BOOKING.COM": 7011,
    "KLOOK": 7011,
    "AIRBNB": 7011,
    # Shopping — MCC 5999
    "LAZADA": 5999,
    "SHOPEE": 5999,
    "AMAZON": 5999,
    "QISAHN": 5999,
    "COURTS": 5200,
    "IKEA": 5200,
    "HARVEY NORMAN": 5200,
}

_THRESHOLD = 80
_CLAUDE_RETRIES = 2
_CLAUDE_RETRY_DELAYS = [1, 2]  # seconds between attempts

_VALID_CATEGORIES = {"FAMILY", "DINING", "OTHER"}

_anthropic_client: "anthropic.Anthropic | None" = None


def _get_client() -> "anthropic.Anthropic":
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic_client


_SYSTEM_PROMPT = (
    "You are a merchant category classifier for Singapore credit cards. "
    "Given a merchant name, respond with exactly one word: "
    "FAMILY, DINING, or OTHER. No explanation."
)


def categorize(merchant: str) -> str:
    name = merchant.upper()
    result = process.extractOne(name, MERCHANT_MCC.keys(), score_cutoff=_THRESHOLD)
    if result:
        mcc = MERCHANT_MCC[result[0]]
        return MCC_CATEGORY.get(mcc, "OTHER")
    return "OTHER"


def categorize_with_claude_fallback(merchant: str) -> str:
    """Fuzzy-match first; call Claude only when the result is OTHER."""
    category = categorize(merchant)
    if category != "OTHER":
        return category

    if not config.ANTHROPIC_API_KEY:
        logger.warning("No ANTHROPIC_API_KEY set; cannot classify '%s' via Claude", merchant)
        return "OTHER"

    client = _get_client()
    for attempt in range(_CLAUDE_RETRIES + 1):
        try:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=10,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": merchant}],
            )
            word = response.content[0].text.strip().upper()
            if word in _VALID_CATEGORIES:
                logger.info("Claude classified '%s' → %s", merchant, word)
                return word
            # Bad response is not retryable
            logger.warning("Claude returned unexpected category '%s' for '%s'", word, merchant)
            return "OTHER"
        except Exception:
            if attempt < _CLAUDE_RETRIES:
                delay = _CLAUDE_RETRY_DELAYS[attempt]
                logger.warning(
                    "Claude fallback attempt %d/%d failed for '%s'; retrying in %ds",
                    attempt + 1, _CLAUDE_RETRIES + 1, merchant, delay,
                )
                time.sleep(delay)
            else:
                import metrics  # late import to avoid circular dependency at module load
                logger.exception("Claude fallback exhausted for merchant '%s'", merchant)
                metrics.claude_failures.inc()

    return "OTHER"
