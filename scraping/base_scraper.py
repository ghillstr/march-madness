"""Base scraper with rate limiting and HTML caching."""

import hashlib
import os
import re
import time

import requests
from bs4 import BeautifulSoup, Comment

from config import CACHE_DIR, REQUEST_DELAY, REQUEST_TIMEOUT, USER_AGENT


class BaseScraper:
    """Base class for all scrapers with rate limiting and caching."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last_request_time = 0
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _cache_path(self, url):
        """Get cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"{url_hash}.html")

    def _rate_limit(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

    def fetch(self, url, use_cache=True):
        """Fetch URL with rate limiting and optional caching."""
        cache_file = self._cache_path(url)

        if use_cache and os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

        self._rate_limit()
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            self._last_request_time = time.time()
            resp.raise_for_status()
            html = resp.text

            if use_cache:
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(html)
            return html
        except requests.RequestException as e:
            print(f"  [ERROR] Failed to fetch {url}: {e}")
            return None

    def parse(self, html):
        """Parse HTML into BeautifulSoup."""
        if html is None:
            return None
        return BeautifulSoup(html, "lxml")

    def fetch_and_parse(self, url, use_cache=True):
        """Fetch and parse in one call."""
        html = self.fetch(url, use_cache)
        return self.parse(html)

    @staticmethod
    def uncomment_tables(soup):
        """Sports Reference hides some tables in HTML comments. Extract them."""
        if soup is None:
            return soup
        comments = soup.find_all(string=lambda t: isinstance(t, Comment))
        for comment in comments:
            if "<table" in str(comment):
                comment_soup = BeautifulSoup(str(comment), "lxml")
                tables = comment_soup.find_all("table")
                if tables:
                    for table in tables:
                        comment.insert_before(table)
                    comment.extract()
        return soup

    @staticmethod
    def clean_school_name(name):
        """Strip trailing suffixes Sports Reference appends to school names (e.g. 'NCAA', 'AP')."""
        return re.sub(r"(NCAA|AP|\d+)\s*$", "", name).strip()

    @staticmethod
    def parse_float(val):
        """Safely parse a float from a table cell."""
        if val is None:
            return None
        text = val.get_text(strip=True) if hasattr(val, "get_text") else str(val).strip()
        if not text or text == "":
            return None
        try:
            return float(text)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def parse_int(val):
        """Safely parse an int from a table cell."""
        if val is None:
            return None
        text = val.get_text(strip=True) if hasattr(val, "get_text") else str(val).strip()
        if not text or text == "":
            return None
        try:
            return int(float(text))
        except (ValueError, TypeError):
            return None
