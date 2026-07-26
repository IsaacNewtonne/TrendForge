"""TrendForge - Web Scraper & Topic Module

Provides topic suggestions based on proven viral categories.
Users can either pick from top 20 or get trending.
"""

import os
import time
import json
import uuid
import hashlib
import html
import re
import feedparser
import requests
from bs4 import BeautifulSoup
from typing import Optional, List, Dict, Any
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from datetime import datetime
from loguru import logger

import yaml

from modules.network_security import configure_system_trust_store

configure_system_trust_store()

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
DEFAULT_TIMEOUT = 30
DEFAULT_DELAY = 2


# ============================================================
# VIRAL TOPICS - Proven categories with high engagement
# ============================================================

VIRAL_TOPICS = {
    "breaking": [
        "major tech company announces",
        "government regulation",
        "stock market crash",
        "celebrity scandal",
        "health warning",
        "climate disaster",
        "military conflict",
        "pandemic update",
    ],
    "money": [
        "making money online",  
        "investment tips",
        "cryptocurrency price",
        "housing market",
        "job market",
        "side hustle",
        "passive income",
        "rich getting richer",
    ],
    "health": [
        "medical breakthrough",
        "diet secret",
        "exercise warning",
        " Supplement",
        "disease cure",
        "longevity research",
        "brain health",
        "sleep optimization",
    ],
    "tech": [
        "artificial intelligence",
        "new smartphone",
        "social media danger",
        "hacking warning",
        "robots taking jobs",
        "量子计算",
        "space technology",
        "electric vehicles",
    ],
    "relationships": [
        "dating app",
        "marriage advice",
        "parenting tips",
        "friend zone",
        "red flags",
        "communication",
        "divorce rate",
        "loneliness epidemic",
    ],
    "privacy": [
        "surveillance state",
        "data tracking",
        "privacy breach",
        "identity theft",
        "smart speaker",
        "phone tracking",
        "online privacy",
        "password security",
    ],
    "career": [
        " job interview",
        "career change",
        "burnout",
        "salary negotiation",
        "remote work",
        "ai replacing workers",
        "networking",
        "leadership",
    ],
    "education": [
        "study tips",
        "learning hack",
        "college debt",
        "online courses",
        "ai homework",
        "student mental health",
        "teaching method",
        "book recommendations",
    ],
    "conspiracy": [
        "government secret",
        "cover up",
        "they don't want",
        "exposed",
        "truth about",
        "hidden agenda",
        "mainstream won't tell",
        "suppressed",
    ],
    "futures": [
        "prediction 2030",
        "coming apocalypse",
        "future technology",
        "文明 collapse",
        "scary forecast",
        "worst case",
        "tipping point",
        "climate future",
    ]
}

# Flatten to top 20 for UI display
def get_top_topics() -> List[str]:
    """Get curated top 20 topics."""
    topics = []
    for category, topic_list in VIRAL_TOPICS.items():
        for t in topic_list[:2]:  # 2 per category = 20
            topics.append(t)
    return topics[:20]


def suggest_similar(topic: str) -> List[str]:
    """Find similar topics from the viral list.
    
    Args:
        topic: User's topic
        
    Returns:
        List of similar topics from curated list
    """
    topic_lower = topic.lower()
    suggestions = []
    
    for category, topic_list in VIRAL_TOPICS.items():
        for t in topic_list:
            if any(word in t.lower() for word in topic_lower.split() if len(word) > 3):
                suggestions.append(t)
    
    return suggestions[:5] if suggestions else []


def load_scraper_config() -> dict:
    """Load scraper configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
            return cfg.get("scraping", {})
    return {}


def load_research_config() -> dict:
    """Load richer research configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
            return cfg.get("research", {})
    return {}


def get_topic(subject: Optional[str] = None) -> str:
    """Get the topic - validate, suggest, or fetch trending.
    
    Args:
        subject: Optional user-provided subject
        
    Returns:
        The topic string to research
        
    Raises:
        ValueError: If topic is too short/invalid and no alternatives
    """
    if subject and subject.strip():
        topic = subject.strip()
        
        # Validate topic quality
        if len(topic) < 2:
            raise ValueError("Topic too short. Minimum 2 characters.")
        
        # Check for similar curated topics
        similar = suggest_similar(topic)
        if similar:
            logger.info(f"Topic '{topic}' - similar curated: {similar[:3]}")
        
        logger.info(f"Using user topic: {topic}")
        return topic
    
    # No subject provided - fetch trending from multiple sources
    topic = fetch_trending_topic()
    if topic:
        logger.info(f"Using trending topic: {topic}")
        return topic
    
    # Final curated fallback
    curated = get_top_topics()
    import random
    fallback = random.choice(curated) if curated else "artificial intelligence"
    logger.info(f"Using curated fallback: {fallback}")
    return fallback


def fetch_trending_topic(region: str = "US") -> Optional[str]:
    """Fetch the current top trending topic from multiple sources.
    
    Args:
        region: Region code (US, GB, AU, etc.)
        
    Returns:
        The trending topic string, or None on failure
    """
    import random
    
    # Try multiple trending sources
    sources = []
    
    # 1. Google Trends (if available)
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload(kw_list=[], timeframe="now 1-d")
        trending = pytrends.trending_searches(pn=f"united_{region.lower()}")
        if not trending.empty:
            sources.append(str(trending.iloc[0, 0]))
    except Exception as e:
        logger.debug(f"Google Trends failed: {e}")
    
    # 2. Reddit trending
    try:
        reddit_results = scrape_reddit("", limit=5)
        for r in reddit_results[:3]:
            title = r.get("title", "")
            if title and len(title) > 10:
                sources.append(title)
    except:
        pass
    
    # 3. X/Twitter trending (if available)
    try:
        # Check environment for credentials
        import os
        if os.getenv("TWEEPY_URL"):
            pass  # Would add tweepy search here
    except:
        pass
    
    # Pick random from sources, or fallback to curated
    if sources:
        return random.choice(sources)
    
    # Fallback to curated list
    curated = get_top_topics()
    fallback = random.choice(curated) if curated else "artificial intelligence"
    logger.info(f"Using curated fallback: {fallback}")
    return fallback


def scrape_web(topic: str, max_sources: int = None, source_plan: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Scrape the web for content related to the topic.
    
    Args:
        topic: The topic to research
        max_sources: Maximum number of sources to fetch
        
    Returns:
        List of content dictionaries with 'source' and 'text' keys
    """
    cfg = load_scraper_config()
    research_cfg = load_research_config()
    max_sources = max_sources or research_cfg.get("target_source_count") or cfg.get("max_sources", 10)
    source_plan = source_plan or {}
    source_plan = {**source_plan, "_topic": topic}
    search_queries = source_plan.get("search_queries") or [topic]
    search_queries = [q for q in search_queries if str(q).strip()][:8]
    specialist_sources = filter_specialist_sources_for_topic(
        source_plan.get("specialist_sources") or [],
        topic,
    )
    
    results = []
    seen_content = set()
    
    logger.info(f"Scraping web for: {topic}")
    
    # 1. Google News RSS
    logger.debug("Fetching Google News...")
    per_query_news = max(2, max_sources // max(1, len(search_queries)) // 2)
    for query in search_queries:
        news_results = scrape_google_news(query, per_query_news)
        for r in news_results:
            append_unique_result(results, seen_content, r, max_sources, source_plan)
        if len(results) >= max_sources:
            break
    
    # Add delay to respect rate limits
    time.sleep(cfg.get("delay", DEFAULT_DELAY))
    
    # 2. Reddit
    logger.debug("Fetching Reddit...")
    reddit_results = scrape_reddit(topic, max(5, max_sources // 4))
    for r in reddit_results:
        append_unique_result(results, seen_content, r, max_sources, source_plan)
    
    time.sleep(cfg.get("delay", DEFAULT_DELAY))
    
    # 3. Wikipedia
    logger.debug("Fetching Wikipedia...")
    wiki_result = scrape_wikipedia(topic)
    if wiki_result and wiki_result["text"]:
        append_unique_result(results, seen_content, wiki_result, max_sources, source_plan)
    
    # 4. Specialist open sources selected by source planner
    if research_cfg.get("specialist_sources", True):
        logger.debug("Fetching specialist open sources...")
        specialist_results = scrape_specialist_sources(topic, search_queries, specialist_sources, max_sources // 3)
        for r in specialist_results:
            append_unique_result(results, seen_content, r, max_sources, source_plan)
            if len(results) >= max_sources:
                break
    
    # 5. Additional web sources
    logger.debug("Fetching additional sources...")
    web_results = scrape_web_generic(topic, max_sources // 4)
    for r in web_results:
        append_unique_result(results, seen_content, r, max_sources, source_plan)
    
    logger.info(f"Scraped {len(results)} unique sources")
    return results[:max_sources]


def append_unique_result(
    results: List[Dict[str, Any]],
    seen_content: set,
    item: Dict[str, Any],
    max_sources: int,
    source_plan: Optional[Dict[str, Any]] = None,
):
    if len(results) >= max_sources:
        return
    text = str(item.get("text", "")).strip()
    if len(text) < 30:
        return
    url = item.get("url", "")
    if source_blocked(url, source_plan or {}):
        return
    if not source_relevant_to_plan(item, source_plan or {}):
        return
    content_hash = hashlib.md5(f"{url}|{text[:600]}".encode("utf-8", errors="ignore")).hexdigest()
    if content_hash in seen_content:
        return
    seen_content.add(content_hash)
    item.setdefault("source_type", infer_source_type(item))
    item.setdefault("domain", urlparse(url).netloc.replace("www.", "") if url else "")
    results.append(item)


def source_blocked(url: str, source_plan: Dict[str, Any]) -> bool:
    if not url:
        return False
    domain = urlparse(url).netloc.replace("www.", "").lower()
    blocked = [str(d).replace("www.", "").lower() for d in source_plan.get("avoid_domains", [])]
    blocked += [str(d).replace("www.", "").lower() for d in load_research_config().get("blocked_source_domains", [])]
    return any(domain.endswith(item) for item in blocked if item)


def infer_source_type(item: Dict[str, Any]) -> str:
    source = str(item.get("source", "")).lower()
    if source in {"arxiv", "pubmed", "github", "government", "sec"}:
        return "specialist"
    if source in {"google_news"}:
        return "news"
    if source == "reddit":
        return "public_discussion"
    if source == "wikipedia":
        return "background"
    return "web"


def filter_specialist_sources_for_topic(sources: List[str], topic: str) -> List[str]:
    normalized = [canonical_specialist_source(source) for source in sources]
    return list(dict.fromkeys(
        source for source in normalized
        if source and specialist_source_fits_topic(source, topic)
    ))


def canonical_specialist_source(source: str) -> str:
    """Defensively normalize planner domain names to scraper source IDs."""
    value = str(source or "").lower().strip()
    value = value.replace("https://", "").replace("http://", "")
    value = value.split("/", 1)[0].replace("www.", "")
    aliases = {
        "arxiv.org": "arxiv",
        "github.com": "github",
        "pubmed.ncbi.nlm.nih.gov": "pubmed",
        "ncbi.nlm.nih.gov": "pubmed",
        "nih.gov": "pubmed",
        "who.int": "who",
        "sec.gov": "sec",
        ".gov": "government",
        "gov": "government",
    }
    if value in aliases:
        return aliases[value]
    if value.endswith(".gov"):
        return "government"
    return value if value in {"arxiv", "github", "pubmed", "who", "sec", "government"} else ""


def specialist_source_fits_topic(source: str, topic: str) -> bool:
    source = str(source or "").lower().strip()
    topic_lower = str(topic or "").lower()
    health_terms = [
        "health",
        "healthcare",
        "medical",
        "medicine",
        "clinical",
        "patient",
        "hospital",
        "disease",
        "cancer",
        "drug",
        "therapy",
        "diagnosis",
        "biotech",
        "pharma",
        "sleep",
        "diet",
        "longevity",
    ]
    tech_terms = ["ai", "artificial intelligence", "machine learning", "robot", "software", "model"]
    finance_terms = ["stock", "company", "crypto", "market", "money", "housing", "earnings", "revenue"]
    policy_terms = ["policy", "regulation", "government", "law", "climate", "energy", "environment"]

    if source in {"pubmed", "who"}:
        return any(term in topic_lower for term in health_terms)
    if source in {"arxiv", "github"}:
        return any(term in topic_lower for term in tech_terms + health_terms + ["science", "research"])
    if source == "sec":
        return any(term in topic_lower for term in finance_terms)
    if source == "government":
        return any(term in topic_lower for term in policy_terms + health_terms + finance_terms)
    return True


def source_relevant_to_plan(item: Dict[str, Any], source_plan: Dict[str, Any]) -> bool:
    """Reject specialist results that are clean sources but outside the topic domain."""
    topic = str(source_plan.get("_topic", ""))
    source = str(item.get("source", "")).lower()
    if source in {"pubmed", "who"} and not specialist_source_fits_topic(source, topic):
        return False

    if source != "pubmed":
        return True

    topic_tokens = content_tokens(topic)
    source_tokens = content_tokens(
        " ".join(str(item.get(key, "")) for key in ("title", "text", "source_name"))
    )
    medical_context = {
        "ai",
        "artificial",
        "intelligence",
        "machine",
        "learning",
        "algorithm",
        "model",
        "software",
    }
    if topic_tokens & source_tokens:
        return True
    return bool(topic_tokens & medical_context and source_tokens & medical_context)


def content_tokens(value: str) -> set[str]:
    stop = {
        "the", "and", "that", "this", "with", "from", "into", "about", "what",
        "when", "where", "which", "would", "could", "should", "there", "their",
        "because", "while", "have", "has", "had", "for", "are", "was", "were",
        "latest", "evidence", "controversy", "expert", "analysis", "public",
        "reaction",
    }
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", str(value).lower())
        if token not in stop
    }


def scrape_google_news(topic: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Fetch news from Google News RSS feed.
    
    Args:
        topic: Topic to search
        limit: Maximum results
        
    Returns:
        List of news content dictionaries
    """
    results = []
    try:
        # Use Google News RSS (no API key needed)
        encoded_topic = quote_plus(topic)
        rss_url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=en-US&gl=US"
        
        feed = feedparser.parse(rss_url)
        
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 TrendForge/1.0"})

        for entry in feed.entries[:limit]:
            # Extract description/summary
            summary = entry.get("summary", entry.get("description", ""))
            title = entry.get("title", "")
            
            # Clean HTML from summary
            summary = clean_html(summary)
            
            source_name = get_feed_source_name(entry)
            google_url = entry.get("link", "")
            publisher_url = resolve_news_publisher_url(
                google_url,
                title,
                source_name,
                session=session,
            )

            if summary and len(summary) > 50 and publisher_url:
                results.append({
                    "source": "google_news",
                    "source_name": source_name,
                    "title": title,
                    "text": summary[:2000],  # Limit length
                    "url": publisher_url,
                    "discovery_url": google_url,
                    "published": entry.get("published", ""),
                    "image_url": get_feed_image_url(entry),
                })
            elif summary and len(summary) > 50:
                logger.debug(f"Discarding unresolved Google News item: {title[:100]}")
    except Exception as e:
        logger.warning(f"Google News scrape failed: {e}")
    
    return results


def resolve_news_publisher_url(
    discovery_url: str,
    title: str,
    source_name: str,
    session: Optional[requests.Session] = None,
) -> str:
    """Resolve an aggregator result to a direct publisher page.

    Google News RSS URLs are useful for discovery but cannot produce reliable
    evidence screenshots. A URL is returned only when it leaves the Google News
    domain and plausibly belongs to the named publisher.
    """
    if not is_google_news_url(discovery_url):
        return discovery_url if is_direct_http_url(discovery_url) else ""

    session = session or requests.Session()
    if str(session.headers.get("User-Agent", "")).lower().startswith("python-requests"):
        session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TrendForge/1.0"
    candidates: List[str] = []
    try:
        response = session.get(
            discovery_url,
            timeout=min(DEFAULT_TIMEOUT, 12),
            allow_redirects=True,
        )
        candidates.append(str(getattr(response, "url", "") or ""))
        candidates.extend(extract_direct_urls_from_html(getattr(response, "text", "") or ""))
    except requests.RequestException as exc:
        logger.debug(f"Google News redirect resolution failed: {exc}")

    direct = choose_publisher_url(candidates, source_name)
    if direct:
        return direct

    clean_title = strip_feed_source_suffix(title, source_name)
    queries = [f'"{clean_title}" {source_name}', f"{clean_title} {source_name}"]
    for query in queries:
        try:
            response = session.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                timeout=min(DEFAULT_TIMEOUT, 12),
            )
            candidates = extract_duckduckgo_result_urls(getattr(response, "text", "") or "")
        except requests.RequestException as exc:
            logger.debug(f"Publisher title lookup failed: {exc}")
            continue
        direct = choose_publisher_url(candidates, source_name)
        if direct:
            return direct
    return ""


def is_google_news_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.netloc.lower().replace("www.", "") == "news.google.com"


def is_direct_http_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not is_google_news_url(value)


def extract_direct_urls_from_html(document: str) -> List[str]:
    decoded = html.unescape(str(document or ""))
    urls = re.findall(r'https?://[^\s"\'<>]+', decoded)
    return [unquote(value).rstrip("),.;") for value in urls]


def extract_duckduckgo_result_urls(document: str) -> List[str]:
    decoded = html.unescape(str(document or ""))
    soup = BeautifulSoup(decoded, "html.parser")
    hrefs = [anchor.get("href", "") for anchor in soup.select("a.result__a")]
    results: List[str] = []
    for href in hrefs:
        query = parse_qs(urlparse(href).query)
        target = query.get("uddg", [href])[0]
        results.append(unquote(target))
    return results


def choose_publisher_url(candidates: List[str], source_name: str) -> str:
    source_tokens = content_tokens(source_name)
    for candidate in candidates:
        if not is_direct_http_url(candidate):
            continue
        domain_tokens = content_tokens(urlparse(candidate).netloc.replace("www.", " ").replace(".", " "))
        if source_tokens and not (source_tokens & domain_tokens):
            continue
        return candidate
    return ""


def strip_feed_source_suffix(title: str, source_name: str) -> str:
    value = str(title or "").strip()
    suffix = str(source_name or "").strip()
    if suffix and value.lower().endswith(f" - {suffix}".lower()):
        return value[: -(len(suffix) + 3)].strip()
    return value


def scrape_reddit(topic: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Fetch posts from Reddit search (no API key required).
    
    Args:
        topic: Topic to search
        limit: Maximum results
        
    Returns:
        List of Reddit post dictionaries
    """
    results = []
    try:
        cfg = load_scraper_config()
        subreddits = cfg.get("reddit_subreddits", ["worldnews", "technology", "science"])
        
        session = requests.Session()
        session.headers.update({
            "User-Agent": "TrendForge/1.0 (https://github.com/trendforge; contact@trendforge.ai)"
        })
        
        for subreddit in subreddits[:3]:  # Limit to 3 subreddits
            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            params = {
                "q": topic,
                "limit": limit,
                "sort": "relevance",
                "restrict_sr": "false"
            }
            
            response = session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                
                for child in data.get("data", {}).get("children", [])[:limit]:
                    post = child.get("data", {})
                    title = post.get("title", "")
                    selftext = post.get("selftext", "")
                    
                    # Use title + selftext
                    content = f"{title}. {selftext}" if selftext else title
                    
                    if content and len(content) > 30:
                        results.append({
                            "source": "reddit",
                            "source_name": f"r/{subreddit}",
                            "title": title,
                            "text": content[:2000],
                            "url": f"https://reddit.com{post.get('permalink', '')}",
                            "image_url": post.get("thumbnail", "") if str(post.get("thumbnail", "")).startswith("http") else "",
                            "score": post.get("score", 0),
                            "num_comments": post.get("num_comments", 0)
                        })
                
                time.sleep(1)  # Rate limit between subreddits
    except Exception as e:
        logger.warning(f"Reddit scrape failed: {e}")
    
    return results


def scrape_wikipedia(topic: str) -> Dict[str, Any]:
    """Fetch summary from Wikipedia.
    
    Args:
        topic: Topic to search
        
    Returns:
        Wikipedia content dictionary
    """
    try:
        import wikipediaapi
        
        wiki = wikipediaapi.Wikipedia("TrendForge/1.0 (https://trendforge.ai)")
        page = wiki.page(topic)
        
        if page.exists():
            return {
                "source": "wikipedia",
                "source_name": "Wikipedia",
                "title": page.title,
                "text": page.summary[:2500],  # Limit length
                "url": page.fullurl,
                "image_url": "",
            }
    except Exception as e:
        logger.warning(f"Wikipedia scrape failed: {e}")
    
    return {"source": "wikipedia", "source_name": "Wikipedia", "title": topic, "text": ""}


def scrape_web_generic(topic: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Generic web scraping for additional content.
    
    Args:
        topic: Topic to search
        limit: Maximum results
        
    Returns:
        List of content dictionaries
    """
    results = []
    
    # Could add more sources here (news APIs, blogs, etc.)
    # For now, this is a placeholder for extensibility
    
    # Example: Search for related terms and fetch from various sources
    try:
        # Use DuckDuckGo instant answer API (no API key)
        session = requests.Session()
        session.headers.update({
            "User-Agent": "TrendForge/1.0"
        })
        
        # Try to get information from related searches
        ddg_url = "https://api.duckduckgo.com/"
        params = {
            "q": topic,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1
        }
        
        response = session.get(ddg_url, params=params, timeout=DEFAULT_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            
            # Abstract text
            abstract = data.get("AbstractText", "")
            if abstract and len(abstract) > 50:
                results.append({
                    "source": "duckduckgo",
                    "source_name": "DuckDuckGo",
                    "title": data.get("Heading", topic),
                    "text": abstract[:2000],
                    "url": data.get("AbstractURL", ""),
                    "image_url": data.get("Image", ""),
                })
            
            # Related topics
            for related in data.get("RelatedTopics", [])[:limit]:
                title = related.get("Text", "")
                url = related.get("URL", "")
                
                if title and len(title) > 30:
                    results.append({
                        "source": "duckduckgo",
                        "source_name": "DuckDuckGo",
                        "title": title[:100],
                        "text": title[:2000],
                        "url": url,
                        "image_url": "",
                    })
    except Exception as e:
        logger.warning(f"Generic web scrape warning: {e}")
    
    return results[:limit]


def scrape_specialist_sources(
    topic: str,
    queries: List[str],
    specialist_sources: List[str],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Fetch topic-specific open sources selected by the planner."""
    selected = {str(source).lower() for source in specialist_sources}
    if not selected:
        topic_lower = topic.lower()
        if any(word in topic_lower for word in ["ai", "machine learning", "robot", "software"]):
            selected.update({"arxiv", "github"})
        if any(word in topic_lower for word in ["health", "medical", "disease", "diet", "sleep"]):
            selected.update({"pubmed", "government"})
        if any(word in topic_lower for word in ["climate", "energy", "environment", "weather"]):
            selected.update({"government"})
        if any(word in topic_lower for word in ["stock", "company", "market", "money", "housing"]):
            selected.update({"sec", "government"})

    results: List[Dict[str, Any]] = []
    query = queries[0] if queries else topic
    per_source = max(2, limit // max(1, len(selected)))

    if "arxiv" in selected:
        results.extend(scrape_arxiv(query, per_source))
    if "github" in selected:
        results.extend(scrape_github_repositories(query, per_source))
    if "pubmed" in selected:
        results.extend(scrape_pubmed(query, per_source))
    if "government" in selected or "who" in selected:
        results.extend(scrape_government_search(query, per_source))
    if "sec" in selected:
        results.extend(scrape_sec_company_search(query, per_source))

    return results[:limit]


def scrape_arxiv(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    results = []
    try:
        url = "http://export.arxiv.org/api/query"
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        response = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        if response.status_code != 200:
            return []
        feed = feedparser.parse(response.text)
        for entry in feed.entries[:limit]:
            summary = clean_html(entry.get("summary", ""))
            title = clean_html(entry.get("title", ""))
            if summary:
                results.append({
                    "source": "arxiv",
                    "source_name": "arXiv",
                    "title": title,
                    "text": summary[:2500],
                    "url": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "image_url": "",
                    "source_type": "specialist",
                })
    except Exception as e:
        logger.warning(f"arXiv scrape failed: {e}")
    return results


def scrape_github_repositories(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    results = []
    try:
        url = "https://api.github.com/search/repositories"
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": limit}
        response = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT, headers={"Accept": "application/vnd.github+json"})
        if response.status_code != 200:
            return []
        for item in response.json().get("items", [])[:limit]:
            description = item.get("description") or ""
            full_name = item.get("full_name") or ""
            stars = item.get("stargazers_count", 0)
            language = item.get("language") or "unknown"
            text = f"{full_name}: {description}. Language: {language}. Stars: {stars}."
            results.append({
                "source": "github",
                "source_name": "GitHub",
                "title": full_name,
                "text": text[:2000],
                "url": item.get("html_url", ""),
                "published": item.get("updated_at", ""),
                "image_url": "",
                "source_type": "specialist",
            })
    except Exception as e:
        logger.warning(f"GitHub scrape failed: {e}")
    return results


def scrape_pubmed(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    results = []
    try:
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        search_params = {"db": "pubmed", "term": query, "retmode": "json", "retmax": limit, "sort": "pub date"}
        search = requests.get(search_url, params=search_params, timeout=DEFAULT_TIMEOUT)
        ids = search.json().get("esearchresult", {}).get("idlist", []) if search.status_code == 200 else []
        if not ids:
            return []
        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        summary = requests.get(summary_url, params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"}, timeout=DEFAULT_TIMEOUT)
        data = summary.json().get("result", {}) if summary.status_code == 200 else {}
        for pmid in ids:
            item = data.get(pmid, {})
            title = item.get("title", "")
            authors = ", ".join(author.get("name", "") for author in item.get("authors", [])[:3])
            text = f"{title}. Authors: {authors}. Journal: {item.get('fulljournalname', '')}."
            results.append({
                "source": "pubmed",
                "source_name": "PubMed",
                "title": title,
                "text": text[:2000],
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "published": item.get("pubdate", ""),
                "image_url": "",
                "source_type": "specialist",
            })
    except Exception as e:
        logger.warning(f"PubMed scrape failed: {e}")
    return results


def scrape_government_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    results = []
    government_queries = [
        f"site:.gov {query}",
        f"site:who.int {query}",
        f"site:noaa.gov {query}",
        f"site:nasa.gov {query}",
    ]
    for gov_query in government_queries[:limit]:
        for item in scrape_web_generic(gov_query, 1):
            item["source"] = "government"
            item["source_name"] = item.get("source_name") or "Open Government Source"
            item["source_type"] = "specialist"
            results.append(item)
            if len(results) >= limit:
                return results
    return results


def scrape_sec_company_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    results = []
    for item in scrape_web_generic(f"site:sec.gov {query}", limit):
        item["source"] = "sec"
        item["source_name"] = "SEC"
        item["source_type"] = "specialist"
        results.append(item)
    return results[:limit]


def get_feed_source_name(entry: Dict[str, Any]) -> str:
    source = entry.get("source")
    if isinstance(source, dict):
        return source.get("title") or source.get("href") or "Google News"
    if source:
        return str(source)
    return "Google News"


def get_feed_image_url(entry: Dict[str, Any]) -> str:
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if isinstance(media, list) and media:
            url = media[0].get("url", "")
            if url:
                return url

    links = entry.get("links", [])
    if isinstance(links, list):
        for link in links:
            if str(link.get("type", "")).startswith("image/") and link.get("href"):
                return link.get("href", "")

    return ""


def clean_html(text: str) -> str:
    """Clean HTML tags from text.
    
    Args:
        text: Text with potential HTML
        
    Returns:
        Cleaned text
    """
    import re
    
    if not text:
        return ""
    
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    
    # Decode HTML entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")
    
    # Clean up whitespace
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    
    return text


def get_source_summary(content: List[Dict[str, Any]]) -> str:
    """Create a summary string of all sources.
    
    Args:
        content: List of content dictionaries
        
    Returns:
        Summary string
    """
    sources = {}
    for item in content:
        src = item.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1
    
    return ", ".join([f"{v} from {k}" for k, v in sources.items()])
