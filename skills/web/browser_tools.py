import webbrowser
import urllib.parse

def open_browser_and_search(query: str) -> str:
    """Opens the default web browser and searches for the given query on Google."""
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded_query}"
        webbrowser.open(url)
        return f"Successfully opened your browser and searched for '{query}'."
    except Exception as e:
        return f"Failed to open browser: {str(e)}"
