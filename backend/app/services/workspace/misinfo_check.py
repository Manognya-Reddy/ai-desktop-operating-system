from urllib.parse import urlparse
import httpx
from app.config import settings

KNOWN_LOW_CREDIBILITY_DOMAINS = {
    "beforeitsnews.com": "known for unverified and fabricated claims",
    "worldtruth.tv": "flagged by multiple fact-checkers for false stories",
    "yournewswire.com": "history of publishing fabricated news",
    "newspunch.com": "history of publishing fabricated news",
    "naturalnews.com": "flagged repeatedly for medical misinformation",
    "infowars.com": "flagged repeatedly by fact-checking organizations",
    "theonion.com": "satire site, not real news",
    "babylonbee.com": "satire site, not real news",
    "empirenews.net": "satire/fabricated news site",
    "nationalreport.net": "history of fabricated stories",
    "huzlers.com": "history of fabricated stories",
    "thedcgazette.com": "flagged for false and misleading claims",
    "dailybuzzlive.com": "history of fabricated stories",
    "newsbiscuit.com": "satire site, not real news",
}

FALSE_RATING_WORDS = (
    "false", "fake", "pants on fire", "misleading", "fabricated",
    "incorrect", "unproven", "no evidence", "hoax", "not true",
)

FACTCHECK_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


def check_domain_list(url):
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        return None
    domain = domain.replace("www.", "")
    reason = KNOWN_LOW_CREDIBILITY_DOMAINS.get(domain)
    if reason:
        return f"this site is {reason}"
    return None


def check_factcheck_api(title):
    if not settings.FACTCHECK_API_KEY or not title:
        return None
    try:
        resp = httpx.get(
            FACTCHECK_URL,
            params={"query": title, "key": settings.FACTCHECK_API_KEY},
            timeout=4.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    claims = data.get("claims", [])
    for claim in claims:
        for review in claim.get("claimReview", []):
            rating = (review.get("textualRating") or "").lower()
            if any(word in rating for word in FALSE_RATING_WORDS):
                publisher = review.get("publisher", {}).get("name", "a fact-checker")
                return f"{publisher} rated a related claim \"{review.get('textualRating')}\""
    return None


def check_url(url, title=None):
    domain_warning = check_domain_list(url)
    if domain_warning:
        return domain_warning
    return check_factcheck_api(title)
