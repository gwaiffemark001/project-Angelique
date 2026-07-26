from ddgs import DDGS

def search_web(query: str) -> str:
    """Searches the live web for real-time information, news, or current events."""
    try:
        with DDGS() as ddgs:
            # Fetch top 3 results to keep context window clean
            results = [r for r in ddgs.text(query, max_results=3)]
            
        if not results:
            return f"I searched the web for '{query}', but I couldn't find any relevant results."
            
        # Format the results cleanly for the LLM to read
        formatted_results = []
        for r in results:
            title = r.get('title', 'No Title')
            body = r.get('body', 'No description')
            href = r.get('href', '')
            formatted_results.append(f"Title: {title}\nSnippet: {body}\nSource: {href}")
            
        return "\n---\n".join(formatted_results)
        
    except Exception as e:
        return f"Web search failed due to a network error: {str(e)}. Please try again in a moment."