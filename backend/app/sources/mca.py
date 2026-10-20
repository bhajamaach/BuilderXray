"""Best-effort lookup of public company/LLP master data on the MCA portal."""
import re
from urllib.parse import urlparse
from pydantic import BaseModel

from .agent import Progress, run_agent

# MCA's deep link redirects through a client-side flow that TinyFish cannot
# reliably load. Start on the official homepage and navigate via MCA Services.
MCA_MASTER_DATA_URL = 'https://www.mca.gov.in/content/mca/global/en/home.html'

class CompanyRecord(BaseModel):
    company_name: str
    cin_or_llpin: str | None = None
    company_status: str | None = None
    date_of_incorporation: str | None = None
    source_url: str
    snippet: str

class MCAResult(BaseModel):
    companies: list[CompanyRecord]
    reason: str | None = None

_NULLABLE = {'type': 'string', 'nullable': True}
SCHEMA = {
    'type': 'object',
    'properties': {
        'companies': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'company_name': {'type': 'string'}, 'cin_or_llpin': _NULLABLE,
            'company_status': _NULLABLE, 'date_of_incorporation': _NULLABLE,
            'source_url': {'type': 'string'}, 'snippet': {'type': 'string'},
        }, 'required': ['company_name', 'source_url', 'snippet']}},
        'reason': _NULLABLE,
    }, 'required': ['companies'],
}

def _tokens(value: str) -> set[str]:
    words = set(re.findall(r'[a-z0-9]+', value.casefold()))
    words.difference_update({'limited', 'ltd', 'private', 'pvt', 'company', 'co', 'llp', 'llc', 'the', 'and'})
    return words

async def check_company(query: str, on_progress: Progress | None = None) -> MCAResult:
    tokens = _tokens(query)
    if len(tokens) < 1 or (re.fullmatch(r'[A-Z0-9/-]{10,24}', query.strip()) and any(char.isdigit() for char in query)):
        raise RuntimeError('Enter a company name rather than a RERA number to check MCA master data.')
    goal = (
        'On the official Ministry of Corporate Affairs (MCA) India homepage, open the '
        'MCA Services menu, then Master Data Services, then View Company/LLP Master Data. '
        'Use the public name search to search this exact name: '
        f'"{query}". Return only records visibly shown by the official MCA site. '
        'For each record extract legal company/LLP name, CIN or LLPIN if shown, company status '
        'if shown, incorporation date if shown, the exact MCA page URL, and a short supporting snippet. '
        'Do not use third-party company databases, infer a match, or treat no results as proof that '
        'the entity is not registered. If login, CAPTCHA, or a portal error blocks the lookup, return '
        'an empty companies list and explain why.'
    )
    try:
        data = await run_agent(MCA_MASTER_DATA_URL, goal, SCHEMA, max_duration=90, on_progress=on_progress)
        result = MCAResult.model_validate(data)
        matches = []
        for company in result.companies:
            parsed = urlparse(company.source_url)
            if parsed.scheme != 'https' or parsed.hostname not in {'mca.gov.in', 'www.mca.gov.in'}:
                continue
            found = _tokens(company.company_name)
            if tokens and tokens.issubset(found) and company.snippet.strip():
                matches.append(company)
        if not matches:
            return MCAResult(companies=[], reason=result.reason or 'The MCA portal returned no clearly matched official record. This is not evidence that the company is unregistered.')
        return MCAResult(companies=matches[:5], reason=None)
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise RuntimeError(f'MCA master-data check failed: {detail}') from exc
