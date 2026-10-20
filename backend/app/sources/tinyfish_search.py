"""Small wrappers for TinyFish's fast Search and Fetch APIs."""
import os
from typing import Any

import httpx


def _key() -> str:
    key = os.getenv('TINYFISH_API_KEY')
    if not key:
        raise RuntimeError('TINYFISH_API_KEY is not configured')
    return key


async def search_official(query: str, domain: str, purpose: str, limit: int = 8) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8)) as client:
        response = await client.get(
            'https://api.search.tinyfish.ai',
            params={'query': query, 'include_domains': domain, 'location': 'IN', 'language': 'en', 'purpose': purpose},
            headers={'X-API-Key': _key()},
        )
        response.raise_for_status()
        payload = response.json()
    results = payload.get('results', []) if isinstance(payload, dict) else []
    return [item for item in results if isinstance(item, dict)][:limit]


async def fetch_pages(urls: list[str], purpose: str) -> list[dict[str, Any]]:
    if not urls:
        return []
    async with httpx.AsyncClient(timeout=httpx.Timeout(55, connect=8)) as client:
        response = await client.post(
            'https://api.fetch.tinyfish.ai',
            json={'urls': urls[:10], 'format': 'markdown', 'links': True, 'ttl': 0,
                  'per_url_timeout_ms': 45000, 'purpose': purpose},
            headers={'X-API-Key': _key(), 'Content-Type': 'application/json'},
        )
        response.raise_for_status()
        payload = response.json()
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get('results') or payload.get('data') or payload.get('pages')
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        return [payload]
    return []


def page_text(page: dict[str, Any]) -> str:
    """Flatten common Fetch response content fields without assuming one API shape."""
    parts: list[str] = []
    for key in ('markdown', 'content', 'text', 'body', 'html', 'title', 'snippet'):
        value = page.get(key)
        if isinstance(value, str):
            parts.append(value)
    nested = page.get('data')
    if isinstance(nested, dict):
        for key in ('markdown', 'content', 'text', 'body', 'html', 'title', 'snippet'):
            value = nested.get(key)
            if isinstance(value, str):
                parts.append(value)
    return '\n'.join(parts)

