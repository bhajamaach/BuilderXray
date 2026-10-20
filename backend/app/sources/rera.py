"""Fast, source-restricted RERA lookups using TinyFish Search and Fetch."""
import re
from urllib.parse import urlparse

from .agent import Progress
from .tinyfish_search import fetch_pages, page_text, search_official
from pydantic import BaseModel, Field

class PortalComplaint(BaseModel):
    ref: str | None = None
    project: str | None = None
    filed_on: str | None = None
    status: str = 'unknown'
    source_url: str
    snippet: str

class PortalProject(BaseModel):
    name: str
    rera_no: str | None = None
    original_possession: str | None = None
    current_possession: str | None = None
    revisions: int | None = Field(default=None, ge=0)
    source_url: str
    snippet: str
    complaints: list[PortalComplaint] = []

class PortalResult(BaseModel):
    projects: list[PortalProject]
    checked_url: str | None = None
    reason: str | None = None

_NULLABLE_STRING = {'type':'string','nullable':True}
SCHEMA = {'type':'object','properties':{'projects':{'type':'array','items':{'type':'object','properties':{
    'name':{'type':'string'},'rera_no':_NULLABLE_STRING,'original_possession':_NULLABLE_STRING,'current_possession':_NULLABLE_STRING,'revisions':{'type':'integer'},'source_url':{'type':'string'},'snippet':{'type':'string'},
    'complaints':{'type':'array','items':{'type':'object','properties':{'ref':_NULLABLE_STRING,'project':_NULLABLE_STRING,'filed_on':_NULLABLE_STRING,'status':{'type':'string'},'source_url':{'type':'string'},'snippet':{'type':'string'}},'required':['status','source_url','snippet']}}
},'required':['name','revisions','source_url','snippet','complaints']}},'checked_url':_NULLABLE_STRING,'reason':_NULLABLE_STRING},'required':['projects']}

PORTALS = {
    'Haryana': ('https://haryanarera.gov.in/', 'Haryana Real Estate Regulatory Authority', {'haryanarera.gov.in','www.haryanarera.gov.in','hareraggm.gov.in','www.hareraggm.gov.in'}),
    'Delhi': ('https://rera.delhi.gov.in/', 'Real Estate Regulatory Authority for the NCT of Delhi', {'rera.delhi.gov.in','www.rera.delhi.gov.in'}),
}

def _registered_rows(text: str, query_tokens: set[str], query: str, is_rera_id: bool) -> list[PortalProject]:
    """Read records from the official registered-projects table, not its search snippet."""
    lines = [line.strip() for line in text.splitlines() if '|' in line]
    headers = None
    found = []
    for line in lines:
        cells = [re.sub(r'[*`]', '', cell).strip() for cell in line.strip('|').split('|')]
        lowered = [cell.casefold() for cell in cells]
        if 'project name' in lowered and 'builder' in lowered and 'project id' in lowered:
            headers = {name: lowered.index(name) for name in ('project name', 'builder', 'project id')}
            continue
        if not headers or all(not cell or set(cell) <= {'-', ':'} for cell in cells):
            continue
        if max(headers.values()) >= len(cells):
            continue
        project_name = cells[headers['project name']]
        builder = cells[headers['builder']]
        project_id = cells[headers['project id']]
        if not project_name or not project_id:
            continue
        project_tokens = set(re.findall(r'[a-z0-9]+', project_name.casefold()))
        builder_tokens = set(re.findall(r'[a-z0-9]+', builder.casefold()))
        if is_rera_id:
            matched = query.casefold() in project_id.casefold()
        else:
            matched = bool(query_tokens) and (query_tokens.issubset(builder_tokens) or query_tokens.issubset(project_tokens))
        if not matched:
            continue
        row = ' | '.join(cells)
        found.append(PortalProject(name=project_name[:200], rera_no=project_id,
                                   revisions=None, source_url='', snippet=row[:500], complaints=[]))
    return found

async def check_state(query: str, state: str = 'Haryana', on_progress: Progress | None = None) -> PortalResult:
    if state not in PORTALS: raise ValueError(f'Unsupported RERA state: {state}')
    portal_url, portal_name, allowed_hosts = PORTALS[state]
    domain = urlparse(portal_url).hostname
    is_rera_id = bool(re.fullmatch(r'[A-Za-z0-9/-]{8,32}', query.strip()) and any(c.isdigit() for c in query))
    search_query = (f'"{query}"' if is_rera_id else f'"{query}" {state} RERA registered project promoter')
    purpose = f'Find official {state} RERA project registration records matching {query}. Prefer individual project detail pages.'
    try:
        if on_progress: await on_progress('Searching official RERA records')
        results = await search_official(search_query, domain, purpose, limit=8)
        candidates = []
        for item in results:
            url = str(item.get('url') or '')
            parsed = urlparse(url)
            if parsed.scheme == 'https' and parsed.hostname in allowed_hosts:
                candidates.append(item)
        if not candidates:
            return PortalResult(projects=[], checked_url=portal_url,
                                reason=f'TinyFish Search returned no {state} RERA pages for this query. No record was validated; this is not evidence that no record exists.')
        if on_progress: await on_progress(f'Opening {min(5, len(candidates))} official record pages')
        pages = await fetch_pages([str(item['url']) for item in candidates[:5]], purpose)
        pages_by_url = {str(page.get('url') or page.get('requested_url') or ''): page for page in pages}
        projects = []
        tokens = {t for t in re.findall(r'[a-z0-9]+', query.casefold()) if t not in {'limited','ltd','private','pvt','company','the','and','llp'}}
        for item in candidates[:5]:
            url = str(item['url'])
            # Only the official registered-projects table proves a registration. Form previews
            # and monitoring orders may be applications or unrelated case material.
            if 'registered_projects' not in urlparse(url).path.casefold():
                continue
            page = pages_by_url.get(url, {})
            text = page_text(page)
            if not text:
                text = '\n'.join(str(item.get(k) or '') for k in ('title','snippet'))
            if not text.strip():
                continue
            matches = _registered_rows(text, tokens, query, is_rera_id)
            projects.extend(project.model_copy(update={'source_url': url}) for project in matches)
        # De-duplicate pages and keep the result small enough to review.
        unique = {project.rera_no or f'{project.source_url}:{project.name}': project for project in projects}
        return PortalResult(projects=list(unique.values())[:20], checked_url=portal_url,
                            reason=None if unique else f'{portal_name} pages were searched, but no exact project record for {query} could be validated. A missing match is not a clean record.')
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise RuntimeError(f'{state} RERA check failed: {detail}') from exc

async def check_haryana(query: str) -> PortalResult:
    """Backward-compatible alias for existing callers."""
    return await check_state(query, 'Haryana')
