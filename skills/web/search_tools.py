import urllib.parse
import webbrowser
from core import config

try:
    from ddgs import DDGS
except ImportError as e:
    DDGS = None
    print(f"⚠️ [Web] DDGS is not installed: {e}")


def search_web(query: str) -> str:
    """Searches the live web for real-time information, news, or current events."""
    if DDGS:
        try:
            with DDGS() as ddgs:
                results = [r for r in ddgs.text(query, max_results=3)]

            if not results:
                return f"I searched the web for '{query}', but I couldn't find any relevant results."

            formatted_results = []
            for r in results:
                title = r.get("title", "No Title")
                body = r.get("body", "No description")
                href = r.get("href", "")
                formatted_results.append(f"Title: {title}\nSnippet: {body}\nSource: {href}")

            return "\n---\n".join(formatted_results)
        except Exception as e:
            return f"Web search failed due to a network error: {str(e)}. Please try again in a moment."

    try:
            # If running headless without browser, return the URL; otherwise open default browser
            url = config.WEB_SEARCH_BASE_URL + urllib.parse.quote(query)
            try:
                import webbrowser
                webbrowser.open(url)
                return f"Search opened in browser: {url}"
            except Exception:
                return f"Search URL: {url}"
    except Exception as e:
        return f"Web search fallback failed: {e}."
