import webbrowser
import urllib.parse
from core import config

def open_browser_and_search(query: str) -> str:
    """Opens the default web browser and searches for the given query."""
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"{config.WEB_SEARCH_BASE_URL}{encoded_query}"
        webbrowser.open(url)
        return f"Successfully opened your browser and searched for '{query}'."
    except Exception as e:
        return f"Failed to open browser: {str(e)}"
