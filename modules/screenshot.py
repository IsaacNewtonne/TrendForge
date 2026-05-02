"""TrendForge - Intelligent Screenshot Capture Module

Smart screenshot capture that:
- Detects main content area (skip ads, nav, footers)
- Captures multiple sections per URL for variety
- Handles paywalls/slow pages gracefully
- Optimizes for video visuals (clean, focused content)
"""

import os
import json
import shutil
import time
import random
import asyncio
import contextlib
import gc
import io
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, urlunparse
from loguru import logger

from modules.screenshot_vision import evaluate_source_screenshot

SELENIUM_AVAILABLE = False
PLAYWRIGHT_AVAILABLE = False
PLAYWRIGHT_SOURCE_DISABLED_REASON: Optional[str] = None
PLAYWRIGHT_SOURCE_DISABLED_LOGGED = False
SELENIUM_SOURCE_DISABLED_REASON: Optional[str] = None
SELENIUM_SOURCE_DISABLED_LOGGED = False
_LAST_SOURCE_NAVIGATION_AT = 0.0
DOMAIN_SCORE_CACHE_PATH = Path("./temp/source_domain_scores.json")
DOMAIN_FAST_TRACK_MIN_SAMPLES = 3
DOMAIN_FAST_TRACK_MIN_AVG = 85
BLOCKED_PAGE_PATTERNS = [
    "access is temporarily restricted",
    "you've been blocked",
    "you have been blocked",
    "blocked by network security",
    "detected unusual activity",
    "unusual traffic",
    "verify you are human",
    "checking your browser",
    "enable javascript and cookies",
    "captcha",
    "robot check",
    "press & hold",
    "press and hold",
    "not a robot",
]

PAYWALL_PATTERNS = [
    "subscribe to continue",
    "subscription required",
    "already a subscriber",
    "sign in to continue",
    "create an account to continue",
    "continue reading with",
    "this content is for subscribers",
]

COOKIE_PATTERNS = [
    "accept all cookies",
    "cookie preferences",
    "manage cookies",
    "we use cookies",
    "privacy choices",
]

DISMISS_SELECTORS = [
    "button[id*='accept' i]",
    "button[class*='accept' i]",
    "button[aria-label*='accept' i]",
    "button[id*='agree' i]",
    "button[class*='agree' i]",
    "button[id*='cookie' i]",
    "button[class*='cookie' i]",
    "button[aria-label*='close' i]",
    "[class*='modal-close' i]",
    "[class*='close-button' i]",
    "[data-testid*='close' i]",
]

OBSTRUCTIVE_SELECTORS = [
    "[id*='cookie' i]",
    "[class*='cookie' i]",
    "[id*='consent' i]",
    "[class*='consent' i]",
    "[class*='paywall' i]",
    "[id*='paywall' i]",
    "[class*='modal' i]",
    "[role='dialog']",
    "[aria-modal='true']",
    "iframe[src*='ads' i]",
    "[class*='newsletter' i]",
    "[class*='subscribe' i]",
    "[class*='overlay' i]",
    "[class*='sticky' i]",
    "[class*='share' i]",
    "[class*='social' i]",
    "[class*='video' i]",
    "aside",
    "footer",
]

DEPRIORITIZED_URL_TERMS = [
    "reddit.com",
    "twitter.com",
    "x.com/",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "forum",
    "community",
    "comments",
]

PAYWALL_DOMAINS = [
    "nytimes.com",
    "wsj.com",
    "ft.com",
    "economist.com",
    "bloomberg.com",
    "thetimes.co.uk",
]

PREFERRED_SOURCE_DOMAINS = [
    ".gov",
    ".edu",
    "wikipedia.org",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "sec.gov",
    "who.int",
    "nist.gov",
    "oecd.org",
    "github.com",
    "openai.com",
    "microsoft.com",
    "googleblog.com",
    "anthropic.com",
]

ARTICLE_SELECTORS = [
    "article",
    "main article",
    "[role='main'] article",
    "[data-testid*='article' i]",
    "[class*='article' i]",
    "[class*='story' i]",
    "[class*='post-content' i]",
    "[class*='entry-content' i]",
    "[itemprop='articleBody']",
    "main",
]

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.common.exceptions import TimeoutException, WebDriverException
    SELENIUM_AVAILABLE = True
except ImportError as e:
    logger.warning(f"selenium not available: {e}")

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    sync_playwright = None


class PlaywrightSourceBrowser:
    """Small wrapper matching the quit() lifecycle used by visual generation."""

    backend = "playwright"

    def __init__(self, playwright, browser, page):
        self.playwright = playwright
        self.browser = browser
        self.page = page

    def quit(self):
        try:
            self.browser.close()
        finally:
            self.playwright.stop()


def get_browser_binary_path() -> str:
    return r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def find_cached_chromedriver(driver_cache: Path) -> Optional[Path]:
    """Find an existing chromedriver without downloading during generation."""
    roots = [
        driver_cache,
        Path.home() / ".wdm" / "drivers" / "chromedriver",
    ]
    for root in roots:
        if not root.exists():
            continue
        drivers = sorted(
            root.rglob("chromedriver.exe" if os.name == "nt" else "chromedriver"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for driver in drivers:
            if driver.is_file():
                return driver

    path_driver = shutil.which("chromedriver")
    return Path(path_driver) if path_driver else None


def source_url_quality(url: str) -> Dict[str, Any]:
    """Score a URL before launching a browser capture."""
    parsed = urlparse(str(url or ""))
    domain = parsed.netloc.lower().replace("www.", "")
    lower_url = str(url or "").lower()
    score = 50
    reasons: List[str] = []

    if not parsed.scheme.startswith("http") or not domain:
        return {"ok": False, "score": 0, "domain": domain, "reason": "not an HTTP URL"}
    if parsed.path.lower().endswith(".pdf"):
        return {"ok": False, "score": 10, "domain": domain, "reason": "PDF URL is better rendered as a source card"}
    if domain == "news.google.com" and "/rss/articles/" in parsed.path.lower():
        return {"ok": False, "score": 5, "domain": domain, "reason": "Google News RSS redirect pages are unreliable screenshots"}

    if any(term in lower_url for term in DEPRIORITIZED_URL_TERMS):
        score -= 25
        reasons.append("dynamic/social/forum URL")
    if any(domain.endswith(paywall) or paywall in domain for paywall in PAYWALL_DOMAINS):
        score -= 25
        reasons.append("likely paywalled domain")
    if any(term in domain or lower_url.endswith(term) for term in PREFERRED_SOURCE_DOMAINS):
        score += 30
        reasons.append("preferred evidence source")
    if parsed.scheme == "https":
        score += 5

    return {
        "ok": score >= 20,
        "score": max(0, min(score, 100)),
        "domain": domain,
        "reason": ", ".join(reasons) if reasons else "standard web source",
    }


def sort_capture_urls(urls: List[str]) -> List[str]:
    return sorted(urls, key=lambda item: source_url_quality(item).get("score", 0), reverse=True)


def load_domain_score_cache() -> Dict[str, Any]:
    try:
        if DOMAIN_SCORE_CACHE_PATH.exists():
            with open(DOMAIN_SCORE_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def domain_score_summary(domain: str) -> Dict[str, Any]:
    cache = load_domain_score_cache()
    entry = cache.get(domain, {})
    samples = int(entry.get("samples", 0) or 0)
    total = float(entry.get("total_score", 0) or 0)
    return {
        "samples": samples,
        "average": total / samples if samples else 0,
    }


def domain_vision_fast_track_allowed(domain: str) -> bool:
    summary = domain_score_summary(domain)
    return (
        summary["samples"] >= DOMAIN_FAST_TRACK_MIN_SAMPLES
        and summary["average"] >= DOMAIN_FAST_TRACK_MIN_AVG
    )


def update_domain_score_cache(domain: str, score: int, ok: bool) -> None:
    if not domain:
        return
    try:
        cache = load_domain_score_cache()
        entry = cache.setdefault(domain, {"samples": 0, "total_score": 0, "accepted": 0, "rejected": 0})
        entry["samples"] = int(entry.get("samples", 0) or 0) + 1
        entry["total_score"] = float(entry.get("total_score", 0) or 0) + float(score)
        if ok:
            entry["accepted"] = int(entry.get("accepted", 0) or 0) + 1
        else:
            entry["rejected"] = int(entry.get("rejected", 0) or 0) + 1
        DOMAIN_SCORE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DOMAIN_SCORE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def build_chrome_options(profile_dir: Path, headless: bool, browser_binary: str, legacy_headless: bool = False):
    from selenium.webdriver.chrome.options import Options

    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless" if legacy_headless else "--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-blink-features=Automationcontrolled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--noerrdialogs")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--window-size=1440,1000")
    chrome_options.add_argument("--lang=en-US,en")
    chrome_options.add_argument(f"--user-data-dir={profile_dir}")
    chrome_options.add_argument("--remote-debugging-port=0")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-component-update")
    chrome_options.add_argument("--disable-breakpad")
    chrome_options.add_argument("--disable-crash-reporter")
    chrome_options.add_argument("--disable-crashpad")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    chrome_options.add_argument("--disable-features=DownloadableAPI,Crashpad")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    if Path(browser_binary).exists():
        chrome_options.binary_location = browser_binary
    return chrome_options


def concise_webdriver_error(error: Exception) -> str:
    first_line = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
    return first_line[:220]


def selenium_source_disabled_by_env() -> bool:
    return os.getenv("TREND_FORGE_DISABLE_SELENIUM_SOURCE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def playwright_source_disabled_by_env() -> bool:
    return os.getenv("TREND_FORGE_DISABLE_PLAYWRIGHT_SOURCE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def playwright_async_pipe_preflight() -> Tuple[bool, str]:
    """Detect Windows environments where asyncio subprocess pipes are blocked."""
    if os.name != "nt":
        return True, ""

    async def _probe() -> None:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "pass",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    try:
        asyncio.run(_probe())
        return True, ""
    except PermissionError as e:
        return False, concise_webdriver_error(e)
    except OSError as e:
        if getattr(e, "winerror", None) == 5:
            return False, concise_webdriver_error(e)
        return True, ""
    except RuntimeError:
        # An event loop is already active in this thread; skip preflight and attempt startup.
        return True, ""
    except Exception:
        return True, ""


def setup_driver(headless: bool = True) -> Optional[webdriver]:
    """Setup optimized WebDriver for smart screenshot capture."""
    global SELENIUM_SOURCE_DISABLED_REASON, SELENIUM_SOURCE_DISABLED_LOGGED

    if not SELENIUM_AVAILABLE:
        return None
    if selenium_source_disabled_by_env():
        return None
    if SELENIUM_SOURCE_DISABLED_REASON:
        if not SELENIUM_SOURCE_DISABLED_LOGGED:
            logger.warning(f"Selenium source browser unavailable: {SELENIUM_SOURCE_DISABLED_REASON}")
            SELENIUM_SOURCE_DISABLED_LOGGED = True
        return None

    # On some locked-down Windows hosts, Chromium subprocess channels fail with
    # WinError 5. Skip Selenium launch attempts when that condition is present.
    preflight_ok, preflight_reason = playwright_async_pipe_preflight()
    if not preflight_ok:
        SELENIUM_SOURCE_DISABLED_REASON = (
            f"Windows subprocess pipe creation denied ({preflight_reason or 'WinError 5'})"
        )
        logger.warning(f"Selenium source browser unavailable: {SELENIUM_SOURCE_DISABLED_REASON}")
        SELENIUM_SOURCE_DISABLED_LOGGED = True
        return None

    try:
        from selenium.webdriver.chrome.service import Service as ChromeService
        from webdriver_manager.chrome import ChromeDriverManager
        from webdriver_manager.core.driver_cache import DriverCacheManager

        driver_cache = Path("./temp/webdriver").resolve()
        profile_root = Path("./temp/chrome_profiles").resolve()
        profile_dir = profile_root / f"profile_{os.getpid()}_{int(time.time() * 1000)}"
        driver_cache.mkdir(parents=True, exist_ok=True)
        profile_root.mkdir(parents=True, exist_ok=True)
        profile_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("WDM_LOCAL", "1")
        os.environ.setdefault("WDM_CACHE_DIR", str(driver_cache))

        browser_binary = get_browser_binary_path()
        cached_driver = find_cached_chromedriver(driver_cache)

        if cached_driver:
            logger.info(f"Using cached ChromeDriver: {cached_driver}")
            service = ChromeService(str(cached_driver))
        else:
            cache_manager = DriverCacheManager(root_dir=str(driver_cache))
            service = ChromeService(ChromeDriverManager(cache_manager=cache_manager).install())

        last_error = None
        driver = None
        for legacy_headless in (False, True):
            try:
                chrome_options = build_chrome_options(
                    profile_dir / ("legacy" if legacy_headless else "new"),
                    headless,
                    browser_binary,
                    legacy_headless=legacy_headless,
                )
                driver = webdriver.Chrome(options=chrome_options, service=service)
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Chrome startup failed ({'legacy' if legacy_headless else 'new'} headless): "
                    f"{concise_webdriver_error(e)}"
                )
                message = str(e)
                if "Access is denied" in message or "platform_channel.cc" in message:
                    SELENIUM_SOURCE_DISABLED_REASON = concise_webdriver_error(e)
                    SELENIUM_SOURCE_DISABLED_LOGGED = True

        if driver is None:
            raise last_error or RuntimeError("Chrome startup failed")

        driver.set_page_load_timeout(30)
        driver.set_window_size(1440, 1000)
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": (
                        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                    )
                },
            )
        except Exception:
            pass

        return driver
    except Exception as e:
        logger.error(f"WebDriver setup failed: {concise_webdriver_error(e)}")
        return None


def setup_playwright_source_browser(headless: bool = True) -> Optional[PlaywrightSourceBrowser]:
    """Create a Playwright browser for source evidence capture."""
    global PLAYWRIGHT_SOURCE_DISABLED_REASON, PLAYWRIGHT_SOURCE_DISABLED_LOGGED

    if not PLAYWRIGHT_AVAILABLE or sync_playwright is None:
        return None
    if playwright_source_disabled_by_env():
        return None
    if PLAYWRIGHT_SOURCE_DISABLED_REASON:
        if not PLAYWRIGHT_SOURCE_DISABLED_LOGGED:
            logger.warning(f"Playwright source browser unavailable: {PLAYWRIGHT_SOURCE_DISABLED_REASON}")
            PLAYWRIGHT_SOURCE_DISABLED_LOGGED = True
        return None

    preflight_ok, preflight_reason = playwright_async_pipe_preflight()
    if not preflight_ok:
        PLAYWRIGHT_SOURCE_DISABLED_REASON = (
            f"async subprocess pipe creation denied ({preflight_reason or 'WinError 5'})"
        )
        logger.warning(f"Playwright source browser unavailable: {PLAYWRIGHT_SOURCE_DISABLED_REASON}")
        PLAYWRIGHT_SOURCE_DISABLED_LOGGED = True
        return None

    pw = None
    stderr_buffer = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr_buffer):
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-gpu",
                    "--disable-software-rasterizer=false",
                ],
            )
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
        )
        logger.info("Using Playwright Chromium for source screenshots")
        return PlaywrightSourceBrowser(pw, browser, page)
    except Exception as e:
        with contextlib.redirect_stderr(stderr_buffer):
            if pw is not None:
                try:
                    pw.stop()
                except Exception:
                    pass
            gc.collect()
        if getattr(e, "winerror", None) == 5 or "Access is denied" in str(e):
            PLAYWRIGHT_SOURCE_DISABLED_REASON = concise_webdriver_error(e)
            PLAYWRIGHT_SOURCE_DISABLED_LOGGED = True
        logger.warning(f"Playwright source browser unavailable: {concise_webdriver_error(e)}")
        return None


def setup_source_capture_browser(headless: bool = True):
    """Prefer Playwright for source screenshots, fallback to Selenium."""
    browser = setup_playwright_source_browser(headless=headless)
    if browser:
        return browser
    return setup_driver(headless=headless)


def find_main_content(driver: webdriver) -> Optional[Tuple[int, int, int, int]]:
    """Intelligently find main content area (article, main, not ads/nav).
    
    Returns:
        (x, y, width, height) of main content area, or None
    """
    content_selectors = [
        "article", "main", "[role='main']", ".article", ".post", ".content",
        "#article", "#content", "#main-content", ".story", ".entry-content",
        "div[itemprop='articleBody']", ".blog-post", ".news-content"
    ]
    
    for selector in content_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if el.is_displayed():
                    loc = el.location_once_scrolled
                    size = el.size
                    if size.get("height", 0) > 200 and size.get("width", 0) > 300:
                        logger.debug(f"Found main content: {selector}")
                        return (loc["x"], loc["y"], size["width"], size["height"])
        except:
            continue
    
    return None


def scroll_to_section(driver: webdriver, y_position: int, smooth: bool = True):
    """Smooth scroll to a vertical position."""
    if smooth:
        driver.execute_script(f"""
            window.scrollTo({{
                top: {y_position},
                behavior: 'smooth'
            }});
        """)
    else:
        driver.execute_script(f"window.scrollTo(0, {y_position});")


def dismiss_common_overlays(driver: webdriver):
    """Best-effort cleanup for popups before screenshot capture."""
    for selector in DISMISS_SELECTORS:
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, selector)
            for button in buttons[:4]:
                if button.is_displayed() and button.is_enabled():
                    driver.execute_script("arguments[0].click()", button)
                    time.sleep(0.25)
        except Exception:
            continue

    click_texts = [
        "accept all",
        "accept",
        "agree",
        "got it",
        "continue",
        "close",
        "no thanks",
        "not now",
    ]
    for text in click_texts:
        try:
            buttons = driver.find_elements(
                By.XPATH,
                (
                    "//button[contains(translate(normalize-space(.), "
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
                    f"'{text}')]"
                ),
            )
            for button in buttons[:3]:
                if button.is_displayed():
                    button.click()
                    time.sleep(0.3)
                    return
        except Exception:
            continue

    try:
        driver.execute_script("""
            const selectors = arguments[0];
            const clickSelectors = arguments[1];
            for (const selector of clickSelectors) {
              for (const el of document.querySelectorAll(selector)) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                  try { el.click(); } catch (e) {}
                }
              }
            }
            for (const selector of selectors) {
              for (const el of document.querySelectorAll(selector)) {
                if (el === document.body || el === document.documentElement) continue;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                const area = Math.max(0, rect.width) * Math.max(0, rect.height);
                const viewport = window.innerWidth * window.innerHeight;
                if (
                  style.position === 'fixed' ||
                  style.position === 'sticky' ||
                  area > viewport * 0.12
                ) {
                  el.style.setProperty('display', 'none', 'important');
                }
              }
            }
        """, OBSTRUCTIVE_SELECTORS, DISMISS_SELECTORS)
    except Exception:
        pass


def wait_for_source_page_ready(driver: webdriver, timeout: int = 18) -> bool:
    """Wait for readyState, body text, headline, and mostly loaded images."""
    deadline = time.time() + timeout
    stable_hits = 0
    last_text_length = -1

    while time.time() < deadline:
        try:
            state = driver.execute_script("""
                const bodyText = (document.body && document.body.innerText || '').trim();
                const headline = Array.from(document.querySelectorAll('h1, [role="heading"]'))
                  .find(el => el.offsetParent !== null && el.innerText.trim().length > 12);
                const images = Array.from(document.images).filter(img => {
                  const rect = img.getBoundingClientRect();
                  return rect.width > 120 && rect.height > 80;
                });
                const loadedImages = images.filter(img => img.complete && img.naturalWidth > 0);
                return {
                  ready: document.readyState,
                  textLength: bodyText.length,
                  hasHeadline: Boolean(headline),
                  imageRatio: images.length ? loadedImages.length / images.length : 1
                };
            """)
        except Exception:
            time.sleep(0.5)
            continue

        text_length = state.get("textLength", 0)
        stable = abs(text_length - last_text_length) < 80
        last_text_length = text_length
        if stable:
            stable_hits += 1
        else:
            stable_hits = 0

        if (
            state.get("ready") == "complete"
            and text_length >= 400
            and state.get("hasHeadline")
            and state.get("imageRatio", 1) >= 0.65
            and stable_hits >= 2
        ):
            return True

        time.sleep(0.6)

    return False


def hard_block_reason(driver: webdriver) -> str | None:
    """Return a blocking reason if the page is unusable."""
    try:
        text = driver.execute_script("""
            return [
              document.title || '',
              document.body && document.body.innerText || ''
            ].join('\\n').toLowerCase();
        """)
    except Exception:
        return "page text unavailable"

    if any(pattern in text for pattern in BLOCKED_PAGE_PATTERNS):
        return "blocked/bot-check page"
    if any(pattern in text for pattern in PAYWALL_PATTERNS):
        return "paywall/subscription page"
    return None


def inject_clean_source_css(driver: webdriver):
    """Hide common visual clutter before capture."""
    try:
        driver.execute_script("""
            const id = 'trendforge-clean-source-css';
            if (document.getElementById(id)) return;
            const style = document.createElement('style');
            style.id = id;
            style.textContent = `
              [id*="cookie" i],
              [class*="cookie" i],
              [id*="consent" i],
              [class*="consent" i],
              [class*="newsletter" i],
              [id*="newsletter" i],
              [class*="subscribe" i],
              [id*="subscribe" i],
              [class*="paywall" i],
              [id*="paywall" i],
              [class*="modal" i],
              [role="dialog"],
              [aria-modal="true"],
              [class*="overlay" i],
              [class*="share" i],
              [class*="social" i],
              [class*="ad-" i],
              [id*="ad-" i],
              [class*="advert" i],
              [id*="advert" i],
              iframe[src*="ads" i],
              video,
              .OUTBRAIN,
              .taboola {
                display: none !important;
                visibility: hidden !important;
                opacity: 0 !important;
              }
              html, body {
                display: block !important;
                visibility: visible !important;
                opacity: 1 !important;
              }
              body { overflow-x: hidden !important; }
              header[style*="fixed"],
              [class*="sticky" i],
              [style*="position: fixed"],
              [style*="position:fixed"] {
                position: static !important;
              }
            `;
            document.documentElement.appendChild(style);
        """)
    except Exception:
        pass


def find_article_element(driver: webdriver):
    """Find the best article-like element for positioning and validation."""
    try:
        return driver.execute_script("""
            const selectors = arguments[0];
            let best = null;
            let bestScore = 0;
            for (const selector of selectors) {
              for (const el of document.querySelectorAll(selector)) {
                const rect = el.getBoundingClientRect();
                const text = (el.innerText || '').trim();
                if (rect.width < 360 || rect.height < 220 || text.length < 250) continue;
                const hasHeading = Boolean(el.querySelector('h1,h2,[role="heading"]'));
                const hasImage = Boolean(Array.from(el.querySelectorAll('img')).find(img => {
                  const r = img.getBoundingClientRect();
                  return r.width > 160 && r.height > 100;
                }));
                const score = Math.min(text.length / 45, 50) + rect.width / 80 + rect.height / 120 +
                  (hasHeading ? 20 : 0) + (hasImage ? 12 : 0);
                if (score > bestScore) {
                  best = el;
                  bestScore = score;
                }
              }
            }
            return best;
        """, ARTICLE_SELECTORS)
    except Exception:
        return None


def position_article_view(driver: webdriver, article_element=None):
    """Position viewport around source branding, headline, and article opening."""
    try:
        driver.set_window_size(1440, 1000)
        if article_element:
            y = driver.execute_script("""
                const el = arguments[0];
                const h = el.querySelector('h1,h2,[role="heading"]') || el;
                const rect = h.getBoundingClientRect();
                return Math.max(0, rect.top + window.scrollY - 140);
            """, article_element)
        else:
            y = driver.execute_script("""
                const h = document.querySelector('h1,h2,[role="heading"]');
                return h ? Math.max(0, h.getBoundingClientRect().top + window.scrollY - 160) : 0;
            """)
        scroll_to_section(driver, int(y), smooth=False)
        time.sleep(1.0)
    except Exception:
        scroll_to_section(driver, 0, smooth=False)
        time.sleep(1.0)


def get_amp_url(driver: webdriver) -> str:
    try:
        return driver.execute_script("""
            const link = document.querySelector('link[rel="amphtml"]');
            return link ? link.href : '';
        """) or ""
    except Exception:
        return ""


def build_retry_urls(url: str, amp_url: str = "") -> List[str]:
    """Build reader-friendly candidates without rapid-fire source hopping."""
    urls = [url]
    if amp_url and amp_url not in urls:
        urls.append(amp_url)

    parsed = urlparse(url)
    if parsed.netloc.startswith("www."):
        mobile = parsed._replace(netloc="m." + parsed.netloc[4:])
        mobile_url = urlunparse(mobile)
        if mobile_url not in urls:
            urls.append(mobile_url)

    if parsed.path and not parsed.path.rstrip("/").endswith("/amp"):
        amp_path = parsed.path.rstrip("/") + "/amp"
        amp_candidate = urlunparse(parsed._replace(path=amp_path))
        if amp_candidate not in urls:
            urls.append(amp_candidate)

    return urls


def extract_source_page_metadata(driver: webdriver, target_url: str) -> Dict[str, Any]:
    """Extract source context for the evidence manifest."""
    try:
        data = driver.execute_script("""
            const canonical = document.querySelector('link[rel="canonical"]');
            const headline = Array.from(document.querySelectorAll('h1,h2,[role="heading"]'))
              .find(el => el.offsetParent !== null && el.innerText.trim().length > 12);
            const article = Array.from(document.querySelectorAll('article, main, [role="main"]'))
              .find(el => el.offsetParent !== null && (el.innerText || '').trim().length > 250);
            const excerpt = article
              ? (article.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 700)
              : (document.body && document.body.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 700);
            return {
              page_title: document.title || '',
              final_url: location.href || '',
              canonical_url: canonical ? canonical.href : '',
              visible_headline: headline ? headline.innerText.trim() : '',
              text_excerpt: excerpt,
              captured_at: new Date().toISOString()
            };
        """)
    except Exception:
        data = {}

    parsed = urlparse(data.get("final_url") or target_url)
    data["domain"] = parsed.netloc.replace("www.", "")
    data["attempted_url"] = target_url
    return data


def capture_clean_source_screenshot_any(
    browser,
    url: str,
    output_path: Path,
    expected_source: str = "",
    expected_headline: str = "",
    min_score: int = 70,
    max_attempts: int = 3,
    delay_between_attempts: float = 2.0,
    vision_config: Optional[Dict[str, Any]] = None,
    topic: str = "",
) -> Dict[str, Any]:
    """Dispatch source capture to Playwright or Selenium."""
    if getattr(browser, "backend", "") == "playwright":
        return capture_clean_source_screenshot_playwright(
            browser,
            url,
            output_path,
            expected_source=expected_source,
            expected_headline=expected_headline,
            min_score=min_score,
            max_attempts=max_attempts,
            delay_between_attempts=delay_between_attempts,
            vision_config=vision_config,
            topic=topic,
        )
    return capture_clean_source_screenshot(
        browser,
        url,
        output_path,
        expected_source=expected_source,
        expected_headline=expected_headline,
        min_score=min_score,
        max_attempts=max_attempts,
        delay_between_attempts=delay_between_attempts,
        vision_config=vision_config,
        topic=topic,
    )


def capture_clean_source_screenshot_playwright(
    browser: PlaywrightSourceBrowser,
    url: str,
    output_path: Path,
    expected_source: str = "",
    expected_headline: str = "",
    min_score: int = 70,
    max_attempts: int = 3,
    delay_between_attempts: float = 2.0,
    vision_config: Optional[Dict[str, Any]] = None,
    topic: str = "",
) -> Dict[str, Any]:
    """Capture and score a source screenshot with Playwright."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    page = browser.page
    url_quality = source_url_quality(url)
    if not url_quality.get("ok"):
        return {"ok": False, "score": url_quality.get("score", 0), "path": None, "reason": url_quality.get("reason")}

    attempted_urls = sort_capture_urls(build_retry_urls(url))
    best: Dict[str, Any] = {"ok": False, "score": 0, "path": None, "reason": "not attempted"}

    for attempt in range(max_attempts):
        target_url = attempted_urls[min(attempt, len(attempted_urls) - 1)]
        logger.info(f"Source Screenshot Pass {attempt + 1}/{max_attempts}: {target_url}")
        throttle_source_navigation(delay_between_attempts)

        try:
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto(target_url, wait_until="networkidle", timeout=30000)
            wait_for_playwright_source_ready(page, timeout_ms=16000)
            dismiss_playwright_overlays(page)
            clean_playwright_source_page(page)
            if playwright_hard_block_reason(page):
                reason = playwright_hard_block_reason(page) or "blocked page"
                logger.warning(f"Screenshot attempt rejected before capture: {reason}")
                best = {"ok": False, "score": 0, "path": None, "reason": reason}
                continue

            metadata = extract_playwright_source_metadata(page, target_url)
            for strategy in ("content_crop", "article_view", "top_fold"):
                attempt_path = output_path.with_name(
                    f"{output_path.stem}_attempt{attempt + 1}_{strategy}{output_path.suffix}"
                )
                if strategy == "article_view":
                    position_playwright_article_view(page)
                page.screenshot(path=str(attempt_path), full_page=False)
                if strategy == "content_crop":
                    crop_playwright_content_region(page, attempt_path)

                quality = score_playwright_source_screenshot(
                    page,
                    attempt_path,
                    expected_source=expected_source,
                    expected_headline=expected_headline,
                )
                quality["strategy"] = strategy
                quality = apply_vision_gate_if_needed(
                    attempt_path,
                    quality,
                    vision_config,
                    expected_source,
                    expected_headline,
                    target_url,
                    topic,
                )

                domain = metadata.get("domain") or source_url_quality(target_url).get("domain", "")
                update_domain_score_cache(domain, int(quality.get("score", 0) or 0), bool(quality.get("ok")))

                logger.info(
                    f"Screenshot Quality Score: {quality['score']}/100 "
                    f"({strategy}: {quality.get('reason', 'scored')})"
                )

                if quality["score"] >= best.get("score", -1):
                    best = {**quality, "path": str(attempt_path), "metadata": metadata}

                if quality["ok"] and quality["score"] >= min_score:
                    if attempt_path != output_path:
                        import shutil
                        shutil.copy(attempt_path, output_path)
                    return {**quality, "path": str(output_path), "metadata": metadata}

            if attempt == 0:
                amp = get_playwright_amp_url(page)
                for candidate in sort_capture_urls(build_retry_urls(target_url, amp)):
                    if candidate not in attempted_urls:
                        attempted_urls.append(candidate)
        except Exception as e:
            best = {"ok": False, "score": 0, "path": None, "reason": f"capture failed: {e}"}

    return best


def wait_for_playwright_source_ready(page, timeout_ms: int = 16000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    try:
        page.wait_for_function(
            """() => {
                const text = (document.body && document.body.innerText || '').trim();
                const heading = Array.from(document.querySelectorAll('h1,h2,[role="heading"]'))
                  .find(el => el.offsetParent !== null && el.innerText.trim().length > 12);
                return text.length >= 300 && Boolean(heading);
            }""",
            timeout=timeout_ms,
        )
    except Exception:
        pass


def dismiss_playwright_overlays(page) -> None:
    """Click common cookie/close controls before hiding remaining overlays."""
    for selector in DISMISS_SELECTORS:
        try:
            for locator_index in range(min(page.locator(selector).count(), 4)):
                item = page.locator(selector).nth(locator_index)
                if item.is_visible(timeout=500):
                    item.click(timeout=1000)
                    page.wait_for_timeout(200)
        except Exception:
            continue
    try:
        page.evaluate(
            """(selectors) => {
                for (const selector of selectors) {
                  for (const el of document.querySelectorAll(selector)) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                      try { el.click(); } catch (e) {}
                    }
                  }
                }
            }""",
            DISMISS_SELECTORS,
        )
    except Exception:
        pass


def clean_playwright_source_page(page) -> None:
    try:
        page.evaluate(
            """(selectors) => {
                const styleId = 'trendforge-clean-source-css';
                if (!document.getElementById(styleId)) {
                  const style = document.createElement('style');
                  style.id = styleId;
                  style.textContent = `
                    [id*="cookie" i], [class*="cookie" i],
                    [id*="consent" i], [class*="consent" i],
                    [class*="newsletter" i], [id*="newsletter" i],
                    [class*="subscribe" i], [id*="subscribe" i],
                    [class*="paywall" i], [id*="paywall" i],
                    [class*="modal" i], [role="dialog"], [aria-modal="true"],
                    [class*="overlay" i], [class*="share" i], [class*="social" i],
                    [class*="ad-" i], [id*="ad-" i],
                    [class*="advert" i], [id*="advert" i],
                    iframe[src*="ads" i], video, .OUTBRAIN, .taboola {
                      display: none !important;
                      visibility: hidden !important;
                      opacity: 0 !important;
                    }
                    html, body {
                      display: block !important;
                      visibility: visible !important;
                      opacity: 1 !important;
                    }
                    body { overflow-x: hidden !important; }
                    header[style*="fixed"], [class*="sticky" i],
                    [style*="position: fixed"], [style*="position:fixed"] {
                      position: static !important;
                    }
                  `;
                  document.documentElement.appendChild(style);
                }
                for (const selector of selectors) {
                  for (const el of document.querySelectorAll(selector)) {
                    if (el === document.body || el === document.documentElement) continue;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    const area = Math.max(0, rect.width) * Math.max(0, rect.height);
                    const viewport = window.innerWidth * window.innerHeight;
                    if (style.position === 'fixed' || style.position === 'sticky' || area > viewport * 0.12) {
                      el.style.setProperty('display', 'none', 'important');
                    }
                  }
                }
            }""",
            OBSTRUCTIVE_SELECTORS,
        )
    except Exception:
        pass


def playwright_hard_block_reason(page) -> str | None:
    try:
        text = page.evaluate(
            """() => [
                document.title || '',
                document.body && document.body.innerText || ''
            ].join('\\n').toLowerCase()"""
        )
    except Exception:
        return "page text unavailable"
    if any(pattern in text for pattern in BLOCKED_PAGE_PATTERNS):
        return "blocked/bot-check page"
    if any(pattern in text for pattern in PAYWALL_PATTERNS):
        return "paywall/subscription page"
    return None


def position_playwright_article_view(page) -> None:
    try:
        y = page.evaluate(
            """(selectors) => {
                let best = null;
                let bestScore = 0;
                for (const selector of selectors) {
                  for (const el of document.querySelectorAll(selector)) {
                    const rect = el.getBoundingClientRect();
                    const text = (el.innerText || '').trim();
                    if (rect.width < 360 || rect.height < 180 || text.length < 200) continue;
                    const hasHeading = Boolean(el.querySelector('h1,h2,[role="heading"]'));
                    const score = Math.min(text.length / 45, 50) + rect.width / 80 + rect.height / 120 + (hasHeading ? 20 : 0);
                    if (score > bestScore) {
                      best = el;
                      bestScore = score;
                    }
                  }
                }
                const heading = best
                  ? (best.querySelector('h1,h2,[role="heading"]') || best)
                  : document.querySelector('h1,h2,[role="heading"]');
                if (!heading) return 0;
                const rect = heading.getBoundingClientRect();
                return Math.max(0, rect.top + window.scrollY - 140);
            }""",
            ARTICLE_SELECTORS,
        )
        page.evaluate("(y) => window.scrollTo(0, y)", int(y or 0))
        page.wait_for_timeout(700)
    except Exception:
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(500)


def score_playwright_source_screenshot(
    page,
    screenshot_path: Path,
    expected_source: str = "",
    expected_headline: str = "",
) -> Dict[str, Any]:
    block_reason = playwright_hard_block_reason(page)
    if block_reason:
        return {"ok": False, "score": 0, "reason": block_reason}

    dom = page.evaluate(
        """({ expectedSource, expectedHeadline, selectors }) => {
            const bodyText = (document.body && document.body.innerText || '').toLowerCase();
            const title = (document.title || '').toLowerCase();
            const headlineEl = Array.from(document.querySelectorAll('h1,h2,[role="heading"]'))
              .find(el => el.offsetParent !== null && el.innerText.trim().length > 12);
            const headline = headlineEl ? headlineEl.innerText.trim().toLowerCase() : '';
            const visibleParagraph = Array.from(document.querySelectorAll('p')).find(p => {
              const rect = p.getBoundingClientRect();
              return p.offsetParent !== null &&
                p.innerText.trim().length > 80 &&
                rect.bottom > 0 && rect.top < window.innerHeight;
            });
            const visibleImage = Array.from(document.images).find(img => {
              const rect = img.getBoundingClientRect();
              return img.complete && img.naturalWidth > 0 &&
                rect.width > 180 && rect.height > 110 &&
                rect.bottom > 0 && rect.top < window.innerHeight;
            });
            let maxOverlayRatio = 0;
            for (const selector of selectors) {
              for (const el of document.querySelectorAll(selector)) {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' || rect.width < 120 || rect.height < 80) continue;
                const area = Math.max(0, rect.width) * Math.max(0, rect.height);
                const ratio = area / Math.max(1, window.innerWidth * window.innerHeight);
                if (style.position === 'fixed' || style.position === 'sticky' || ratio > 0.12) {
                  maxOverlayRatio = Math.max(maxOverlayRatio, ratio);
                }
              }
            }
            const sourceVisible = expectedSource
              ? bodyText.includes(expectedSource.slice(0, 45)) || title.includes(expectedSource.slice(0, 45))
              : true;
            const headlineVisible = expectedHeadline
              ? headline.includes(expectedHeadline.slice(0, 45)) || bodyText.includes(expectedHeadline.slice(0, 45))
              : Boolean(headline);
            return {
              sourceVisible,
              headlineVisible,
              hasContent: Boolean(visibleParagraph || visibleImage),
              hasHeadline: Boolean(headline),
              bodyLength: bodyText.length,
              maxOverlayRatio,
            };
        }""",
        {
            "expectedSource": (expected_source or "").lower(),
            "expectedHeadline": (expected_headline or "").lower(),
            "selectors": OBSTRUCTIVE_SELECTORS,
        },
    )

    blank_ratio = screenshot_blank_ratio(screenshot_path)
    if dom.get("bodyLength", 0) < 300:
        return {"ok": False, "score": 0, "reason": "page body is too small/empty", "blank_ratio": blank_ratio}
    if blank_ratio > 0.85:
        return {"ok": False, "score": 0, "reason": f"mostly blank screenshot ({blank_ratio:.0%})", "blank_ratio": blank_ratio}
    score = 0
    reasons = []
    if dom.get("headlineVisible") or dom.get("hasHeadline"):
        score += 30
    else:
        reasons.append("headline missing")
    if dom.get("sourceVisible"):
        score += 20
    else:
        reasons.append("source branding missing")
    if dom.get("hasContent") or dom.get("bodyLength", 0) > 700:
        score += 25
    else:
        reasons.append("article body/image missing")
    if dom.get("maxOverlayRatio", 0) > 0.35:
        reasons.append("large fixed element visible")
    if blank_ratio <= 0.35:
        score += 15
    elif blank_ratio <= 0.50:
        score += 8
        reasons.append("high blank area")
    if dom.get("bodyLength", 0) > 1000:
        score += 10

    return {
        "ok": score >= 70,
        "score": min(score, 100),
        "reason": ", ".join(reasons) if reasons else "video-ready",
        "blank_ratio": blank_ratio,
    }


def crop_playwright_content_region(page, screenshot_path: Path) -> bool:
    """Crop screenshot to the richest visible article/content region when possible."""
    try:
        region = page.evaluate(
            """(selectors) => {
                function contentBounds(el, fallbackRect) {
                  const blocks = Array.from(el.querySelectorAll('h1,h2,h3,p,li,blockquote,figure,table,img')).filter(block => {
                    const rect = block.getBoundingClientRect();
                    const style = window.getComputedStyle(block);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    if (rect.bottom <= 0 || rect.top >= window.innerHeight || rect.width < 120 || rect.height < 16) return false;
                    const tag = block.tagName.toLowerCase();
                    const text = (block.innerText || block.alt || '').trim();
                    if (tag === 'img') return block.complete && block.naturalWidth > 0 && rect.width > 160 && rect.height > 90;
                    if (tag === 'figure' || tag === 'table') return rect.width > 180 && rect.height > 80;
                    return text.length > (tag.startsWith('h') ? 6 : 35);
                  });
                  if (!blocks.length) return fallbackRect;
                  let left = window.innerWidth;
                  let top = window.innerHeight;
                  let right = 0;
                  let bottom = 0;
                  for (const block of blocks.slice(0, 16)) {
                    const rect = block.getBoundingClientRect();
                    left = Math.min(left, Math.max(0, rect.left));
                    top = Math.min(top, Math.max(0, rect.top));
                    right = Math.max(right, Math.min(window.innerWidth, rect.right));
                    bottom = Math.max(bottom, Math.min(window.innerHeight, rect.bottom));
                  }
                  return { left, top, right, bottom };
                }
                let best = null;
                let bestScore = 0;
                for (const selector of selectors) {
                  for (const el of document.querySelectorAll(selector)) {
                    const rect = el.getBoundingClientRect();
                    const text = (el.innerText || '').trim();
                    if (rect.width < 360 || rect.height < 160 || text.length < 180) continue;
                    const visibleW = Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0);
                    const visibleH = Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0);
                    if (visibleW < 280 || visibleH < 120) continue;
                    const hasHeading = Boolean(el.querySelector('h1,h2,[role="heading"]'));
                    const score = Math.min(text.length / 30, 70) + visibleW / 50 + visibleH / 80 + (hasHeading ? 20 : 0);
                    if (score > bestScore) {
                      const bounds = contentBounds(el, rect);
                      bestScore = score;
                      best = {
                        x: Math.max(0, bounds.left - 34),
                        y: Math.max(0, bounds.top - 34),
                        width: Math.min(window.innerWidth - Math.max(0, bounds.left - 34), (bounds.right - bounds.left) + 68),
                        height: Math.min(window.innerHeight - Math.max(0, bounds.top - 34), (bounds.bottom - bounds.top) + 68)
                      };
                    }
                  }
                }
                return best;
            }""",
            ARTICLE_SELECTORS,
        )
        if not region:
            return False

        from PIL import Image

        image = Image.open(screenshot_path).convert("RGB")
        scale_x = image.width / 1440
        scale_y = image.height / 1000
        left = max(0, int(float(region["x"]) * scale_x))
        top = max(0, int(float(region["y"]) * scale_y))
        right = min(image.width, int((float(region["x"]) + float(region["width"])) * scale_x))
        bottom = min(image.height, int((float(region["y"]) + float(region["height"])) * scale_y))
        if right - left < 300 or bottom - top < 160:
            return False
        image.crop((left, top, right, bottom)).resize((1440, 1000), Image.Resampling.LANCZOS).save(screenshot_path)
        return True
    except Exception:
        return False


def extract_playwright_source_metadata(page, target_url: str) -> Dict[str, Any]:
    try:
        data = page.evaluate(
            """() => {
                const canonical = document.querySelector('link[rel="canonical"]');
                const headline = Array.from(document.querySelectorAll('h1,h2,[role="heading"]'))
                  .find(el => el.offsetParent !== null && el.innerText.trim().length > 12);
                const article = Array.from(document.querySelectorAll('article, main, [role="main"]'))
                  .find(el => el.offsetParent !== null && (el.innerText || '').trim().length > 250);
                const excerpt = article
                  ? (article.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 700)
                  : (document.body && document.body.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 700);
                return {
                  page_title: document.title || '',
                  final_url: location.href || '',
                  canonical_url: canonical ? canonical.href : '',
                  visible_headline: headline ? headline.innerText.trim() : '',
                  text_excerpt: excerpt,
                  captured_at: new Date().toISOString()
                };
            }"""
        )
    except Exception:
        data = {}
    parsed = urlparse(data.get("final_url") or target_url)
    data["domain"] = parsed.netloc.replace("www.", "")
    data["attempted_url"] = target_url
    return data


def get_playwright_amp_url(page) -> str:
    try:
        return page.evaluate("() => document.querySelector('link[rel=\"amphtml\"]')?.href || ''") or ""
    except Exception:
        return ""


def capture_clean_source_screenshot(
    driver: webdriver,
    url: str,
    output_path: Path,
    expected_source: str = "",
    expected_headline: str = "",
    min_score: int = 70,
    max_attempts: int = 3,
    delay_between_attempts: float = 2.0,
    vision_config: Optional[Dict[str, Any]] = None,
    topic: str = "",
) -> Dict[str, Any]:
    """Run the full Source Screenshot Pass and return score/result metadata."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    url_quality = source_url_quality(url)
    if not url_quality.get("ok"):
        return {"ok": False, "score": url_quality.get("score", 0), "path": None, "reason": url_quality.get("reason")}

    attempted_urls = sort_capture_urls(build_retry_urls(url))
    best: Dict[str, Any] = {"ok": False, "score": 0, "path": None, "reason": "not attempted"}

    for attempt in range(max_attempts):
        target_url = attempted_urls[min(attempt, len(attempted_urls) - 1)]
        logger.info(f"Source Screenshot Pass {attempt + 1}/{max_attempts}: {target_url}")
        throttle_source_navigation(delay_between_attempts)

        try:
            driver.set_window_size(1440, 1000)
            driver.get(target_url)
        except Exception as e:
            best = {"ok": False, "score": 0, "path": None, "reason": f"navigation failed: {e}"}
            continue

        wait_for_source_page_ready(driver)
        dismiss_common_overlays(driver)
        inject_clean_source_css(driver)
        dismiss_common_overlays(driver)
        time.sleep(0.8)

        block_reason = hard_block_reason(driver)
        if block_reason:
            logger.warning(f"Screenshot attempt rejected before capture: {block_reason}")
            amp = get_amp_url(driver)
            for candidate in build_retry_urls(target_url, amp):
                if candidate not in attempted_urls:
                    attempted_urls.append(candidate)
            best = {"ok": False, "score": 0, "path": None, "reason": block_reason}
            continue

        article = find_article_element(driver)
        position_article_view(driver, article)
        inject_clean_source_css(driver)
        time.sleep(0.7)

        metadata = extract_source_page_metadata(driver, target_url)
        for strategy in ("content_crop", "article_view", "top_fold"):
            if strategy == "top_fold":
                scroll_to_section(driver, 0, smooth=False)
                time.sleep(0.5)
            elif strategy == "article_view":
                position_article_view(driver, article)
                time.sleep(0.5)

            attempt_path = output_path.with_name(f"{output_path.stem}_attempt{attempt + 1}_{strategy}{output_path.suffix}")
            try:
                driver.save_screenshot(str(attempt_path))
                if strategy == "content_crop":
                    crop_selenium_content_region(driver, attempt_path)
            except Exception as e:
                best = {"ok": False, "score": 0, "path": None, "reason": f"capture failed: {e}"}
                continue

            quality = score_source_screenshot(
                driver,
                attempt_path,
                expected_source=expected_source,
                expected_headline=expected_headline,
                article_element=article,
            )
            quality["strategy"] = strategy
            quality = apply_vision_gate_if_needed(
                attempt_path,
                quality,
                vision_config,
                expected_source,
                expected_headline,
                target_url,
                topic,
            )

            domain = metadata.get("domain") or source_url_quality(target_url).get("domain", "")
            update_domain_score_cache(domain, int(quality.get("score", 0) or 0), bool(quality.get("ok")))

            logger.info(
                f"Screenshot Quality Score: {quality['score']}/100 "
                f"({strategy}: {quality.get('reason', 'scored')})"
            )

            if quality["score"] > best.get("score", 0):
                best = {**quality, "path": str(attempt_path), "metadata": metadata}

            if quality["ok"] and quality["score"] >= min_score:
                if attempt_path != output_path:
                    import shutil
                    shutil.copy(attempt_path, output_path)
                return {**quality, "path": str(output_path), "metadata": metadata}

        if attempt == 0:
            amp = get_amp_url(driver)
            for candidate in sort_capture_urls(build_retry_urls(target_url, amp)):
                if candidate not in attempted_urls:
                    attempted_urls.append(candidate)

    return best


def merge_vision_quality(dom_quality: Dict[str, Any], vision_quality: Dict[str, Any]) -> Dict[str, Any]:
    """Require both deterministic and vision gates to pass."""
    dom_score = int(dom_quality.get("score", 0))
    vision_score = int(vision_quality.get("score", 0))
    ok = bool(dom_quality.get("ok")) and bool(vision_quality.get("ok"))
    reason = dom_quality.get("reason", "scored")
    if not vision_quality.get("ok"):
        reason = f"vision rejected: {vision_quality.get('reason', 'quality too low')}"
    elif vision_quality.get("reason"):
        reason = f"{reason}; vision: {vision_quality.get('reason')}"

    return {
        **dom_quality,
        "ok": ok,
        "score": min(dom_score, vision_score),
        "reason": reason,
        "vision": vision_quality,
    }


def apply_vision_gate_if_needed(
    screenshot_path: Path,
    quality: Dict[str, Any],
    vision_config: Optional[Dict[str, Any]],
    expected_source: str,
    expected_headline: str,
    source_url: str,
    topic: str,
) -> Dict[str, Any]:
    """Run vision QA unless a strong domain cache allows fast-track."""
    if not (vision_config or {}).get("vision_quality_gate", False) or not quality.get("ok"):
        return quality

    domain = source_url_quality(source_url).get("domain", "")
    if (vision_config or {}).get("vision_fast_track", False) and domain and domain_vision_fast_track_allowed(domain):
        summary = domain_score_summary(domain)
        return {
            **quality,
            "reason": f"{quality.get('reason', 'scored')}; vision fast-tracked for {domain} ({summary['average']:.0f}/100 avg)",
            "vision": {
                "ok": True,
                "score": int(summary["average"]),
                "reason": "domain cache fast-track",
                "domain": domain,
            },
        }

    vision_quality = evaluate_source_screenshot(
        screenshot_path,
        vision_config or {},
        expected_source=expected_source,
        expected_headline=expected_headline,
        source_url=source_url,
        topic=topic,
    )
    return merge_vision_quality(quality, vision_quality)


def throttle_source_navigation(min_delay: float):
    """Avoid rapid-fire source requests across the shared browser session."""
    global _LAST_SOURCE_NAVIGATION_AT
    elapsed = time.time() - _LAST_SOURCE_NAVIGATION_AT
    if _LAST_SOURCE_NAVIGATION_AT and elapsed < min_delay:
        time.sleep(min_delay - elapsed)
    _LAST_SOURCE_NAVIGATION_AT = time.time()


def score_source_screenshot(
    driver: webdriver,
    screenshot_path: Path,
    expected_source: str = "",
    expected_headline: str = "",
    article_element=None,
) -> Dict[str, Any]:
    """Score screenshot readiness for video use."""
    block_reason = hard_block_reason(driver)
    if block_reason:
        return {"ok": False, "score": 0, "reason": block_reason}
    if not page_is_video_ready(driver):
        return {"ok": False, "score": 0, "reason": "DOM quality gate failed"}

    dom = driver.execute_script("""
        const expectedSource = (arguments[0] || '').toLowerCase();
        const expectedHeadline = (arguments[1] || '').toLowerCase();
        const article = arguments[2];
        const bodyText = (document.body && document.body.innerText || '').toLowerCase();
        const headlineEl = Array.from(document.querySelectorAll('h1,h2,[role="heading"]'))
          .find(el => el.offsetParent !== null && el.innerText.trim().length > 12);
        const headline = headlineEl ? headlineEl.innerText.trim().toLowerCase() : '';
        const articleText = article ? (article.innerText || '').toLowerCase() : bodyText;
        const visibleImage = Array.from(document.images).find(img => {
          const rect = img.getBoundingClientRect();
          return img.complete && img.naturalWidth > 0 &&
            rect.width > 180 && rect.height > 110 &&
            rect.bottom > 0 && rect.top < window.innerHeight;
        });
        const visibleParagraph = Array.from(document.querySelectorAll('p')).find(p => {
          const rect = p.getBoundingClientRect();
          return p.offsetParent !== null &&
            p.innerText.trim().length > 80 &&
            rect.bottom > 0 && rect.top < window.innerHeight;
        });
        const sourceVisible = expectedSource
          ? bodyText.includes(expectedSource) || document.title.toLowerCase().includes(expectedSource)
          : true;
        const headlineVisible = expectedHeadline
          ? headline.includes(expectedHeadline.slice(0, 45)) || bodyText.includes(expectedHeadline.slice(0, 45))
          : Boolean(headline);
        return {
          sourceVisible,
          headlineVisible,
          hasContent: Boolean(visibleImage || visibleParagraph),
          hasHeadline: Boolean(headline),
          articleTextLength: articleText.length,
          viewportTextLength: bodyText.length
        };
    """, expected_source, expected_headline, article_element)

    blank_ratio = screenshot_blank_ratio(screenshot_path)
    if blank_ratio > 0.85:
        return {"ok": False, "score": 0, "reason": f"mostly blank screenshot ({blank_ratio:.0%})"}

    score = 0
    reasons = []
    if dom.get("headlineVisible") or dom.get("hasHeadline"):
        score += 25
    else:
        reasons.append("headline missing")
    if dom.get("sourceVisible"):
        score += 20
    else:
        reasons.append("source branding missing")
    if dom.get("hasContent") or dom.get("articleTextLength", 0) > 500:
        score += 20
    else:
        reasons.append("article body/image missing")
    if page_is_video_ready(driver):
        score += 15
    if blank_ratio <= 0.35:
        score += 10
    elif blank_ratio <= 0.50:
        score += 5
        reasons.append("high blank area")
    if dom.get("viewportTextLength", 0) > 700:
        score += 10
    else:
        reasons.append("text density low")

    return {
        "ok": score >= 70,
        "score": min(score, 100),
        "reason": ", ".join(reasons) if reasons else "video-ready",
        "blank_ratio": blank_ratio,
    }


def screenshot_blank_ratio(path: Path) -> float:
    """Estimate how much of a screenshot is blank white/black space."""
    try:
        from PIL import Image

        image = Image.open(path).convert("RGB").resize((240, 160))
        pixels = list(image.getdata())
        blank = 0
        for r, g, b in pixels:
            bright_blank = r > 242 and g > 242 and b > 242
            dark_blank = r < 12 and g < 12 and b < 12
            low_contrast = max(r, g, b) - min(r, g, b) < 5
            if (bright_blank or dark_blank) and low_contrast:
                blank += 1
        return blank / max(1, len(pixels))
    except Exception:
        return 0.0


def crop_selenium_content_region(driver: webdriver, screenshot_path: Path) -> bool:
    """Crop Selenium screenshot around the strongest visible article region."""
    try:
        region = driver.execute_script(
            """
            const selectors = arguments[0];
            function contentBounds(el, fallbackRect) {
              const blocks = Array.from(el.querySelectorAll('h1,h2,h3,p,li,blockquote,figure,table,img')).filter(block => {
                const rect = block.getBoundingClientRect();
                const style = window.getComputedStyle(block);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                if (rect.bottom <= 0 || rect.top >= window.innerHeight || rect.width < 120 || rect.height < 16) return false;
                const tag = block.tagName.toLowerCase();
                const text = (block.innerText || block.alt || '').trim();
                if (tag === 'img') return block.complete && block.naturalWidth > 0 && rect.width > 160 && rect.height > 90;
                if (tag === 'figure' || tag === 'table') return rect.width > 180 && rect.height > 80;
                return text.length > (tag.startsWith('h') ? 6 : 35);
              });
              if (!blocks.length) return fallbackRect;
              let left = window.innerWidth;
              let top = window.innerHeight;
              let right = 0;
              let bottom = 0;
              for (const block of blocks.slice(0, 16)) {
                const rect = block.getBoundingClientRect();
                left = Math.min(left, Math.max(0, rect.left));
                top = Math.min(top, Math.max(0, rect.top));
                right = Math.max(right, Math.min(window.innerWidth, rect.right));
                bottom = Math.max(bottom, Math.min(window.innerHeight, rect.bottom));
              }
              return { left, top, right, bottom };
            }
            let best = null;
            let bestScore = 0;
            for (const selector of selectors) {
              for (const el of document.querySelectorAll(selector)) {
                const rect = el.getBoundingClientRect();
                const text = (el.innerText || '').trim();
                if (rect.width < 360 || rect.height < 160 || text.length < 180) continue;
                const visibleW = Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0);
                const visibleH = Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0);
                if (visibleW < 280 || visibleH < 120) continue;
                const hasHeading = Boolean(el.querySelector('h1,h2,[role="heading"]'));
                const score = Math.min(text.length / 30, 70) + visibleW / 50 + visibleH / 80 + (hasHeading ? 20 : 0);
                if (score > bestScore) {
                  const bounds = contentBounds(el, rect);
                  bestScore = score;
                  best = {
                    x: Math.max(0, bounds.left - 34),
                    y: Math.max(0, bounds.top - 34),
                    width: Math.min(window.innerWidth - Math.max(0, bounds.left - 34), (bounds.right - bounds.left) + 68),
                    height: Math.min(window.innerHeight - Math.max(0, bounds.top - 34), (bounds.bottom - bounds.top) + 68),
                    viewportWidth: window.innerWidth,
                    viewportHeight: window.innerHeight
                  };
                }
              }
            }
            return best;
            """,
            ARTICLE_SELECTORS,
        )
        if not region:
            return False

        from PIL import Image

        image = Image.open(screenshot_path).convert("RGB")
        viewport_width = max(1, float(region.get("viewportWidth") or 1440))
        viewport_height = max(1, float(region.get("viewportHeight") or 1000))
        scale_x = image.width / viewport_width
        scale_y = image.height / viewport_height
        left = max(0, int(float(region["x"]) * scale_x))
        top = max(0, int(float(region["y"]) * scale_y))
        right = min(image.width, int((float(region["x"]) + float(region["width"])) * scale_x))
        bottom = min(image.height, int((float(region["y"]) + float(region["height"])) * scale_y))
        if right - left < 300 or bottom - top < 160:
            return False
        image.crop((left, top, right, bottom)).resize((image.width, image.height), Image.Resampling.LANCZOS).save(screenshot_path)
        return True
    except Exception:
        return False


def page_is_video_ready(driver: webdriver) -> bool:
    """Reject blocked, paywalled, empty, or visually obstructed pages."""
    try:
        quality = driver.execute_script("""
            const text = (document.body && document.body.innerText || '').toLowerCase();
            const title = (document.title || '').toLowerCase();
            const h1 = Array.from(document.querySelectorAll('h1'))
              .find(el => el.offsetParent !== null && el.innerText.trim().length > 12);
            const selectors = arguments[0];
            let maxOverlayRatio = 0;
            let overlayCount = 0;
            for (const selector of selectors) {
              for (const el of document.querySelectorAll(selector)) {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                if (
                  style.display === 'none' ||
                  style.visibility === 'hidden' ||
                  rect.width < 120 ||
                  rect.height < 80
                ) {
                  continue;
                }
                const area = Math.max(0, rect.width) * Math.max(0, rect.height);
                const ratio = area / Math.max(1, window.innerWidth * window.innerHeight);
                if (style.position === 'fixed' || style.position === 'sticky' || ratio > 0.12) {
                  overlayCount += 1;
                  maxOverlayRatio = Math.max(maxOverlayRatio, ratio);
                }
              }
            }
            return {
              text,
              title,
              hasHeadline: Boolean(h1),
              bodyLength: text.length,
              overlayCount,
              maxOverlayRatio
            };
        """, OBSTRUCTIVE_SELECTORS)
    except Exception as e:
        logger.warning(f"Screenshot quality check failed: {e}")
        return False

    text = f"{quality.get('title', '')}\n{quality.get('text', '')}"
    if quality.get("bodyLength", 0) < 400:
        logger.warning("Screenshot rejected: page body is too small/empty")
        return False
    if any(pattern in text for pattern in BLOCKED_PAGE_PATTERNS):
        logger.warning("Screenshot rejected: blocked-access page detected")
        return False
    if any(pattern in text for pattern in PAYWALL_PATTERNS):
        logger.warning("Screenshot rejected: paywall/subscription prompt detected")
        return False
    if quality.get("maxOverlayRatio", 0) > 0.20:
        logger.warning("Screenshot rejected: large overlay detected")
        return False
    if quality.get("overlayCount", 0) > 2 and any(pattern in text for pattern in COOKIE_PATTERNS):
        logger.warning("Screenshot rejected: cookie/consent overlays detected")
        return False
    if not quality.get("hasHeadline"):
        logger.warning("Screenshot rejected: no visible headline detected")
        return False

    return True


def capture_smarter(
    driver: webdriver,
    url: str,
    output_path: Path,
    capture_strategy: str = "auto"
) -> bool:
    """Capture intelligent screenshot with strategy.
    
    Strategies:
    - "auto": Main content, then scroll sections
    - "hero": Top fold / headline
    - "full": Full page
    - "sections": Multiple scroll positions
    """
    try:
        driver.get(url)
        
        # Wait for initial content
        time.sleep(2)
        
        # Try to wait for body
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except:
            pass
        
        dismiss_common_overlays(driver)
        
        # Check for paywall blocks
        try:
            paywall = driver.find_elements(By.CSS_SELECTOR, 
                ".paywall, .paywall-block, [class*='paywall'], .locked-content")
            if paywall and any(el.is_displayed() for el in paywall):
                logger.warning(f"Paywall detected: {url}")
                # Try to bypass or fallback
                pass
        except:
            pass
        
        # Scroll to top first
        scroll_to_section(driver, 0)
        time.sleep(1)
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Get viewport for cropping
        viewport = driver.execute_script("""
            return {
                w: window.innerWidth,
                h: window.innerHeight,
                d: document.documentElement.scrollHeight
            };
        """)
        
        doc_h = viewport["d"]
        win_h = viewport["h"]
        win_w = viewport["w"]
        
        # Smart capture based on strategy
        if capture_strategy == "hero":
            # Hero / above fold
            driver.save_screenshot(str(output_path))
            logger.debug(f"Hero screenshot: {output_path}")
            return True
            
        elif capture_strategy == "full":
            # Full page - set tall window
            driver.set_window_size(win_w, min(doc_h, 5400))
            time.sleep(0.5)
            driver.save_screenshot(str(output_path))
            logger.debug(f"Full page screenshot: {output_path}")
            return True
            
        elif capture_strategy == "sections":
            # Capture at multiple scroll positions for variety
            base_path = output_path.parent / output_path.stem
            
            # Calculate sections: top, middle, bottom
            positions = [
                (0, "top"),
                (max(0, doc_h // 2 - win_h // 2), "middle"),
                (max(0, doc_h - win_h), "bottom")
            ]
            
            saved = []
            for y, name in positions:
                scroll_to_section(driver, y)
                time.sleep(0.8)
                
                section_path = output_path.parent / f"{base_path.stem}_{name}.png"
                driver.save_screenshot(str(section_path))
                saved.append(str(section_path))
            
            # Copy main output as top
            import shutil
            if saved:
                shutil.copy(saved[0], output_path)
            
            logger.debug(f"Section screenshots: {saved}")
            return True if saved else False
        
        else:  # "auto" - smart detection
            # Try to find main content area
            content = find_main_content(driver)
            
            if content:
                x, y, w, h = content
                # Scroll to show content
                scroll_to_section(driver, max(0, y - 100))
                time.sleep(0.8)
                
                driver.set_window_size(min(w + 100, 1920), min(h + 200, 1080))
                time.sleep(0.3)
                driver.save_screenshot(str(output_path))
                logger.debug(f"Smart content screenshot: {output_path}")
                return True
            
            # Fallback: hero screenshot
            scroll_to_section(driver, 0)
            time.sleep(0.5)
            driver.save_screenshot(str(output_path))
            return True
            
    except Exception as e:
        logger.error(f"Smart capture failed: {e}")
        return False


def capture_screenshot_sets(
    url: str,
    base_output: Path,
    num_captures: int = 3,
    driver: Optional[webdriver] = None
) -> List[str]:
    """Capture multiple screenshots from a single URL for video variety.
    
    Args:
        url: Source URL
        base_output: Base output path (stem used for naming)
        num_captures: Number of unique screenshots to capture
        
    Returns:
        List of screenshot file paths
    """
    owns_driver = driver is None
    captured = []
    
    try:
        if driver is None:
            driver = setup_driver()
        if not driver:
            logger.warning(f"No driver for {url}")
            return []
        
        logger.info(f"Capturing {num_captures} shots from: {url}")
        
        # If we want multiple captures, use section strategy
        if num_captures > 1:
            driver.get(url)
            time.sleep(2)
            
            doc_h = driver.execute_script("return document.documentElement.scrollHeight")
            win_h = driver.execute_script("return window.innerHeight")
            
            # Calculate positions
            positions = []
            for i in range(min(num_captures, 4)):
                pos = int((doc_h / (num_captures + 1)) * (i + 1)) - win_h // 2
                positions.append(max(0, pos))
            
            base_path = base_output.parent / base_output.stem
            
            for i, y in enumerate(positions):
                driver.execute_script(f"window.scrollTo(0, {y});")
                time.sleep(1)
                
                out_path = base_output.parent / f"{base_path.stem}_{i+1}.png"
                driver.save_screenshot(str(out_path))
                captured.append(str(out_path))
            
            # Main output
            import shutil
            if captured:
                shutil.copy(captured[0], base_output)
                captured.insert(0, str(base_output))
            
        else:
            # Single capture
            if capture_smarter(driver, url, base_output, "auto"):
                captured = [str(base_output)]
        
        logger.info(f"Captured {len(captured)} screenshots")
        return captured
        
    except Exception as e:
        logger.error(f"Capture set failed: {e}")
        return []
    finally:
        if owns_driver and driver:
            driver.quit()


def is_selenium_available() -> bool:
    return SELENIUM_AVAILABLE


# ========== BACKWARD COMPATIBLE WRAPPER ==========

def capture_screenshots_from_content(
    content: List[Dict[str, Any]], 
    output_dir: Path = Path("./temp/screenshots"),
    max_urls: int = 5,
    captures_per_url: int = 1
) -> List[str]:
    """Capture intelligent screenshots for content items.
    
    Args:
        content: List of content items with URLs
        output_dir: Output directory
        max_urls: Maximum URLs to capture (default 5 for speed)
        captures_per_url: Captures per URL (default 1)
    """
    if not SELENIUM_AVAILABLE:
        logger.warning("selenium not available - skipping screenshot capture")
        return []
    
    # Limit to max_urls for speed
    content = content[:max_urls]
    logger.info(f"Capturing screenshots for {len(content)} URLs (max {max_urls})")
    screenshot_paths = []
    output_dir.mkdir(parents=True, exist_ok=True)
    
    driver = None
    try:
        driver = setup_driver()
        if not driver:
            logger.warning("No driver available")
            return []
        
        for i, item in enumerate(content):
            url = item.get("url", "")
            source = item.get("source", "unknown")
            
            if not url or not url.startswith("http"):
                logger.debug(f"Skipping {i} - invalid URL")
                continue
            
            # Smart filename approach
            filename = f"{source}_{i:03d}.png"
            output_path = output_dir / filename
            
            logger.info(f"Capturing {i+1}/{len(content)}: {url}")
            
            # Use faster capture with 1 capture per URL
            captures = capture_screenshot_sets(
                url,
                output_path,
                num_captures=captures_per_url,
                driver=driver,
            )
            
            if captures:
                screenshot_paths.extend(captures)
                logger.info(f"Captured {len(captures)} shots")
            else:
                # Final fallback
                if capture_smarter(driver, url, output_path, "hero"):
                    screenshot_paths.append(str(output_path))
            
            time.sleep(1)
        
        logger.info(f"Smart captured {len(screenshot_paths)} images")
        return screenshot_paths
        
    except Exception as e:
        logger.error(f"Screenshot pipeline error: {e}")
        return screenshot_paths
    finally:
        if driver:
            driver.quit()
