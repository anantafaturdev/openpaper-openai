import logging
import os

from firecrawl import FirecrawlApp

logger = logging.getLogger(__name__)


def _get_firecrawl_app() -> FirecrawlApp:
    """Lazily initialize the Firecrawl client. Only fails when actually used."""
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        raise ValueError("FIRECRAWL_API_KEY environment variable is not set.")
    return FirecrawlApp(api_key=api_key)


def scrape_web_page(url: str) -> str:
    """
    Scrape the content of a web page using Firecrawl.

    Args:
        url (str): The URL of the web page to scrape.

    Returns:
        str: The scraped content of the web page.
    """
    try:
        app = _get_firecrawl_app()
        # firecrawl-py 4.x: scrape() returns a Document (with .markdown) on
        # success and raises on failure. There is no .error attribute.
        document = app.scrape(url, formats=["markdown"])
        if document.markdown:
            return document.markdown
        raise Exception(f"Failed to scrape {url}: no markdown content returned")
    except Exception as e:
        # Scrape failures are expected (anti-bot walls, dead links) and the
        # caller logs them at warning; don't also log at error here.
        raise Exception(f"Error scraping {url}: {str(e)}")
