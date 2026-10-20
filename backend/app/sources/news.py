"""TinyFish Search/Fetch adapter. Results remain unclassified until an analyst is configured."""
import os, httpx

async def search_news(query: str) -> list[dict]:
    key = os.getenv('TINYFISH_API_KEY')
    if not key: raise RuntimeError('TINYFISH_API_KEY is not configured')
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get('https://api.search.tinyfish.ai', params={'query': f'"{query}" builder real estate delay litigation India', 'location':'IN', 'language':'en'}, headers={'X-API-Key':key})
        response.raise_for_status()
        return response.json().get('results', [])[:8]
