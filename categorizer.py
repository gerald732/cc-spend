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
import re
import time
from rapidfuzz import process
import anthropic
from google import genai
from google.genai import types as genai_types, errors as genai_errors
import config
import database
import metrics

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
_LLM_RETRIES = 2
_LLM_RETRY_DELAYS = [1, 2]  # seconds between attempts

_VALID_CATEGORIES = {"FAMILY", "DINING", "OTHER"}

_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
_GEMINI_MODEL = "gemini-2.5-flash-lite"

_claude_cache: list = []   # holds at most one Anthropic client
_gemini_cache: list = []   # holds at most one GenerativeModel

_SYSTEM_PROMPT = (
    "You are a merchant category classifier for Singapore credit cards. "
    "Given a merchant name, respond with exactly one word: "
    "FAMILY, DINING, or OTHER. No explanation."
)

_CORP_SUFFIX_RE = re.compile(
    r"\b(PTE\.?\s*LTD\.?|SDN\s*BHD|LLP|PLC|INC\.?|LTD\.?|CORP\.?)\s*$",
    re.IGNORECASE,
)


def _strip_corp_suffix(merchant: str) -> str:
    """Remove common corporate suffixes before sending to an LLM."""
    return _CORP_SUFFIX_RE.sub("", merchant).strip()


def _get_claude_client() -> "anthropic.Anthropic":
    """Return the shared Anthropic client, initialising it on first call."""
    if not _claude_cache:
        _claude_cache.append(anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY))
    return _claude_cache[0]


def _get_gemini_client() -> "genai.Client":
    """Return the shared Gemini Client, initialising it on first call."""
    if not _gemini_cache:
        _gemini_cache.append(genai.Client(api_key=config.GEMINI_API_KEY))
    return _gemini_cache[0]


def categorize(merchant: str) -> str:
    """Fuzzy-match merchant name against known MCC mappings; return category or 'OTHER'."""
    name = merchant.upper()
    result = process.extractOne(name, MERCHANT_MCC.keys(), score_cutoff=_THRESHOLD)
    if result:
        mcc = MERCHANT_MCC[result[0]]
        return MCC_CATEGORY.get(mcc, "OTHER")
    return "OTHER"


def _classify_with_claude(merchant: str) -> str:
    """Call Claude API to classify merchant; returns a valid category or 'OTHER'."""
    query = _strip_corp_suffix(merchant)
    logger.info("Calling Claude for merchant '%s' (query: '%s')", merchant, query)
    client = _get_claude_client()
    word = None
    for attempt in range(_LLM_RETRIES + 1):
        try:
            response = client.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=10,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": query}],
            )
            raw = response.content[0].text.strip()
            word = raw.upper()
            logger.info("Claude raw response for '%s': %r → parsed as %s", merchant, raw, word)
            if word not in _VALID_CATEGORIES:
                logger.warning(
                    "Claude returned unexpected value %r for '%s'; defaulting to OTHER",
                    raw, merchant,
                )
                return "OTHER"
            break
        except anthropic.BadRequestError as exc:
            logger.error("Claude non-retryable error for '%s': %s", merchant, exc)
            metrics.claude_failures.inc()
            return "OTHER"
        except Exception:
            if attempt < _LLM_RETRIES:
                delay = _LLM_RETRY_DELAYS[attempt]
                logger.warning(
                    "Claude attempt %d/%d failed for '%s'; retrying in %ds",
                    attempt + 1, _LLM_RETRIES + 1, merchant, delay,
                )
                time.sleep(delay)
            else:
                logger.exception("Claude exhausted retries for merchant '%s'", merchant)
                metrics.claude_failures.inc()
                return "OTHER"
    if word:
        database.upsert_merchant_category(merchant, word, "claude")
    return word or "OTHER"


def _classify_with_gemini(merchant: str) -> str:
    """Call Gemini API to classify merchant; returns a valid category or 'OTHER'."""
    query = _strip_corp_suffix(merchant)
    logger.info("Calling Gemini for merchant '%s' (query: '%s')", merchant, query)
    client = _get_gemini_client()
    word = None
    for attempt in range(_LLM_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=_GEMINI_MODEL,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    max_output_tokens=10,
                ),
                contents=query,
            )
            raw = response.text.strip()
            word = raw.upper()
            logger.info("Gemini raw response for '%s': %r → parsed as %s", merchant, raw, word)
            if word not in _VALID_CATEGORIES:
                logger.warning(
                    "Gemini returned unexpected value %r for '%s'; defaulting to OTHER",
                    raw, merchant,
                )
                return "OTHER"
            break
        except genai_errors.ClientError as exc:
            if exc.code != 429:
                logger.error("Gemini non-retryable error for '%s': %s", merchant, exc)
                metrics.claude_failures.inc()
                return "OTHER"
            if attempt < _LLM_RETRIES:
                delay = _LLM_RETRY_DELAYS[attempt]
                logger.warning(
                    "Gemini attempt %d/%d failed for '%s'; retrying in %ds",
                    attempt + 1, _LLM_RETRIES + 1, merchant, delay,
                )
                time.sleep(delay)
            else:
                logger.exception("Gemini exhausted retries for merchant '%s'", merchant)
                metrics.claude_failures.inc()
                return "OTHER"
        except Exception:
            if attempt < _LLM_RETRIES:
                delay = _LLM_RETRY_DELAYS[attempt]
                logger.warning(
                    "Gemini attempt %d/%d failed for '%s'; retrying in %ds",
                    attempt + 1, _LLM_RETRIES + 1, merchant, delay,
                )
                time.sleep(delay)
            else:
                logger.exception("Gemini exhausted retries for merchant '%s'", merchant)
                metrics.claude_failures.inc()
                return "OTHER"
    if word:
        database.upsert_merchant_category(merchant, word, "gemini")
    return word or "OTHER"


def categorize_with_llm_fallback(merchant: str) -> str:
    """Fuzzy-match first; check cache; call Gemini or Claude for unknowns."""
    category = categorize(merchant)
    if category != "OTHER":
        return category

    cached = database.get_merchant_category(merchant)
    if cached is not None:
        logger.info("Cache hit: '%s' → %s", merchant, cached)
        return cached

    if config.GEMINI_API_KEY:
        return _classify_with_gemini(merchant)
    if config.ANTHROPIC_API_KEY:
        return _classify_with_claude(merchant)

    logger.warning("No LLM API key configured; cannot classify '%s'", merchant)
    return "OTHER"
