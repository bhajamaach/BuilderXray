import asyncio, ipaddress, json, os, uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from urllib.parse import urlparse
from .models import Report, CheckRequest, Source
from .score import score_report

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / 'data' / 'reports'
FIXTURES = ROOT.parent / 'fixtures'
jobs: dict[str, dict] = {}
reports: dict[str, Report] = {}
live_today = 0
live_day = datetime.now(timezone.utc).date()
ip_runs: dict[str, list[datetime]] = {}

def load_reports():
    DATA.mkdir(parents=True, exist_ok=True)
    for path in list(FIXTURES.glob('*.json')) + list(DATA.glob('*.json')):
        try:
            report = Report.model_validate_json(path.read_text())
            from .sources.court import ECOURTS_URL, ECOURTS_REASON
            from .sources.rera import PORTALS
            rera_id_for_report = 'rera_dl' if report.state == 'Delhi' else 'rera_hr'
            from .sources.mca import MCA_MASTER_DATA_URL
            migrated = []
            for source in report.sources:
                update = {}
                if source.id == rera_id_for_report:
                    update['url'] = PORTALS[report.state][0]
                    if report.mode == 'live' and source.status == 'not_checked' and 'check failed' in (source.reason or '').casefold():
                        update['status'] = 'failed'
                if source.id == 'court':
                    if source.reason == 'Coming next': update['reason'] = ECOURTS_REASON
                    if not source.url or source.reason == 'Coming next': update['url'] = ECOURTS_URL
                if source.id == 'registry':
                    if source.reason == 'Coming next':
                        update['reason'] = ('This older report predates the live MCA lookup. Open MCA Services → Master Data Services → View Company/LLP Master Data.'
                                            if report.mode == 'live' else 'Saved run; no MCA lookup was made. Open the official master-data service to check manually.')
                    if not source.url or source.reason == 'Coming next': update['url'] = MCA_MASTER_DATA_URL
                migrated.append(source.model_copy(update=update))
            report.sources = migrated
            report = score_report(report)
            reports[report.id] = report
        except Exception: pass

def fixture_for(query: str, state: str = 'Haryana') -> Report | None:
    q = query.casefold()
    candidates = [r for r in reports.values() if r.state == state and r.mode == 'saved']
    if not candidates: return None
    return next((r for r in candidates if r.builder_name.casefold() in q or q in r.builder_name.casefold()), candidates[0])

async def run_job_safe(job_id: str, req: CheckRequest, ip: str):
    try:
        await run_job(job_id, req, ip)
    except Exception as exc:
        job = jobs.get(job_id)
        if not job: return
        message = str(exc).replace(os.getenv('TINYFISH_API_KEY','__no_key__'), '[redacted]')[:500]
        event = {'event':'error','data':{'message':message or 'The check could not be completed.'}}
        job['history'].append(event)
        job['status'] = 'error'
        job['error'] = event['data']['message']
        await job['queue'].put(event)
        await job['queue'].put(None)

async def run_job(job_id: str, req: CheckRequest, ip: str):
    global live_today, live_day
    queue = jobs[job_id]['queue']
    rera_id = 'rera_dl' if req.state == 'Delhi' else 'rera_hr'
    rera_label = 'Delhi RERA' if req.state == 'Delhi' else 'Haryana RERA'
    async def emit(kind, data):
        event = {'event':kind,'data':data}
        jobs[job_id]['history'].append(event)
        if kind in ('step','source','progress') and jobs[job_id]['status'] == 'starting':
            jobs[job_id]['status'] = 'running'
        if kind == 'step': jobs[job_id]['steps'].append(data['text'])
        elif kind == 'source': jobs[job_id]['sources'][data['id']] = {'status':data['status'], 'reason':data.get('reason'), 'url':data.get('url')}
        elif kind == 'done': jobs[job_id]['status'] = 'done'; jobs[job_id]['report_id'] = data['report_id']
        elif kind == 'error': jobs[job_id]['status'] = 'error'; jobs[job_id]['error'] = data.get('message')
        await queue.put(event)
    await emit('step', {'text':'Resolving builder name'})
    await asyncio.sleep(.15)
    saved = req.mode == 'saved' or os.getenv('DEMO_MODE','auto') == 'replay'
    limit = int(os.getenv('MAX_LIVE_RUNS_PER_DAY','30'))
    today = datetime.now(timezone.utc).date()
    if today != live_day:
        live_today, live_day = 0, today
    configured = bool(os.getenv('TINYFISH_API_KEY'))
    live_passcode = os.getenv('LIVE_PASSCODE')
    try: local_run = ipaddress.ip_address(ip).is_loopback
    except ValueError: local_run = False
    authorized = configured and (local_run or (bool(live_passcode) and req.passcode == live_passcode))
    if req.mode == 'live' and not authorized:
        message = 'TinyFish is not connected' if not configured else 'Live access code is not valid'
        await emit('error', {'message':message}); await queue.put(None); return
    recent_ip_runs = [at for at in ip_runs.get(ip, []) if at > datetime.now(timezone.utc) - timedelta(hours=1)]
    ip_runs[ip] = recent_ip_runs
    if not (configured and authorized) or live_today >= limit or len(recent_ip_runs) >= 3: saved = True
    if saved:
        await emit('step', {'text':'Using a saved example; no external sources will be contacted'})
        from .sources.court import ECOURTS_URL, ECOURTS_REASON
        await emit('source', {'id':rera_id,'status':'not_checked','reason':'Saved run; no live portal check was made'})
        await emit('source', {'id':'news','status':'not_checked','reason':'Saved run; no live news search was made'})
        await emit('source', {'id':'court','status':'not_checked','reason':ECOURTS_REASON,'url':ECOURTS_URL})
        from .sources.mca import MCA_MASTER_DATA_URL
        await emit('source', {'id':'registry','status':'not_checked','reason':'Saved run; no MCA lookup was made. Open the official master-data service to check manually.','url':MCA_MASTER_DATA_URL})
        fixture = fixture_for(req.query, req.state)
        if fixture:
            report = fixture.model_copy(deep=True, update={'id':job_id,'builder_query':req.query,'state':req.state,'mode':'saved','generated_at':datetime.now(timezone.utc)})
            report.summary = f'Saved {req.state} example from {report.generated_at.date().isoformat()}. {report.summary}'
            report.sources = [source for source in report.sources if source.id not in {'court','registry'}]
            report.sources.extend([
                Source(id='court',label='Court records',status='not_checked',reason=ECOURTS_REASON,url=ECOURTS_URL),
                Source(id='registry',label='Company registry',status='not_checked',reason='Saved run; no MCA lookup was made. Open the official master-data service to check manually.',url=MCA_MASTER_DATA_URL),
            ])
        else:
            now = datetime.now(timezone.utc)
            report = Report(id=job_id,builder_query=req.query,builder_name=req.query,state=req.state,mode='saved',generated_at=now,verdict='unknown',score=0,summary=f'No saved {req.state} example is available for this builder. No live check was made.',sources=[Source(id=rera_id,label=rera_label,status='not_checked',reason='Saved run; no live portal check was made',checked_at=now),Source(id='news',label='News search',status='not_checked',reason='Saved run; no live news search was made',checked_at=now),Source(id='court',label='Court records',status='not_checked',reason=ECOURTS_REASON,url=ECOURTS_URL),Source(id='registry',label='Company registry',status='not_checked',reason='Saved run; no MCA lookup was made. Open the official master-data service to check manually.',url=MCA_MASTER_DATA_URL)])
    else:
        live_today += 1
        ip_runs[ip].append(datetime.now(timezone.utc))
        now = datetime.now(timezone.utc)
        from .sources.rera import PORTALS
        await emit('source', {'id':rera_id,'status':'running','url':PORTALS[req.state][0]})
        await emit('source', {'id':'news','status':'running'})
        from .sources.court import ECOURTS_URL
        await emit('source', {'id':'court','status':'not_checked','reason':'Official eCourts search requires a CAPTCHA; open the official portal to complete it manually.','url':ECOURTS_URL})
        from .sources.mca import MCA_MASTER_DATA_URL
        await emit('source', {'id':'registry','status':'not_checked','reason':'MCA name search is protected by a CAPTCHA. Open the official portal to complete this check manually.','url':MCA_MASTER_DATA_URL})
        await emit('step', {'text':f'Sending the builder query to {rera_label}'})
        await emit('step', {'text':'Searching public news for related reports'})
        from .sources.news import search_news
        from .sources.rera import check_state
        async def progress_for(label):
            async def report_progress(text): await emit('progress', {'text':f'{label} · {text}'})
            return report_progress
        rera_task = asyncio.create_task(check_state(req.query,req.state,on_progress=await progress_for(rera_label)))
        news_task = asyncio.create_task(search_news(f'{req.query} {req.state}'))
        pending = {rera_task:'RERA portal',news_task:'news search'}
        results = {}
        elapsed = 0
        while pending:
            finished, _ = await asyncio.wait(pending, timeout=4, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                label = pending.pop(task)
                try:
                    results[label] = task.result()
                    await emit('step', {'text':f'{label} returned; validating its result'})
                except Exception as exc:
                    results[label] = exc
                    await emit('step', {'text':f'{label} could not be read; recording it as not checked'})
            if pending:
                elapsed += 4
                await emit('progress', {'text':f'Waiting for {" and ".join(pending.values())} · {elapsed}s'})
        rera_result, news_result = results['RERA portal'], results['news search']
        from datetime import date
        from .models import Source, Claim, Project, Complaint
        claims, projects, complaints = [], [], []
        rera_ok = not isinstance(rera_result, Exception)
        reason = str(rera_result) if not rera_ok else None
        if rera_ok:
            for item in rera_result.projects:
                if not _is_rera_url(item.source_url,req.state):
                    rera_ok = False; reason = f'Portal result included an invalid or non-{req.state} source URL.'; claims.clear(); projects.clear(); complaints.clear(); break
                claim_id = f'c{len(claims)+1}'
                claims.append(Claim(id=claim_id,text=f'{rera_label} lists {item.name} for {req.query}.',source_id=rera_id,source_url=item.source_url,snippet=item.snippet[:500]))
                projects.append(Project(name=item.name,rera_no=item.rera_no,original_possession=_as_date(item.original_possession),current_possession=_as_date(item.current_possession),revisions=item.revisions,claim_ids=[claim_id]))
                for c in item.complaints:
                    if not _is_rera_url(c.source_url,req.state):
                        continue
                    cid=f'c{len(claims)+1}'
                    claims.append(Claim(id=cid,text=f'{rera_label} complaint record for {c.project or item.name} is marked {c.status}.',source_id=rera_id,source_url=c.source_url,snippet=c.snippet[:500]))
                    status=c.status.casefold()
                    complaints.append(Complaint(ref=c.ref,project=c.project,filed_on=_as_date(c.filed_on),status=status if status in ('pending','resolved') else 'unknown',claim_id=cid))
            if rera_ok and not projects:
                rera_ok=False;reason='No projects were returned for this builder; absence of results is not treated as a clean record.'
        rera_status='partial' if rera_ok else 'failed'
        if rera_ok:
            reason = 'Official registered-project records matched. Possession dates and complaint records were not validated, so the risk verdict is not assessed.'
        news_status='not_checked' if isinstance(news_result,Exception) else 'partial'
        news_reason='TinyFish search completed; news needs Claude classification and source-page validation before it can support claims.' if news_status=='partial' else str(news_result)
        registry_records = []
        registry_reason = 'MCA name search is protected by a CAPTCHA. Open the official portal to complete this check manually.'
        registry_status = 'not_checked'
        registry_url = MCA_MASTER_DATA_URL
        mca_claims = []
        for company in registry_records:
            details = [company.company_name]
            if company.cin_or_llpin: details.append(f'CIN/LLPIN {company.cin_or_llpin}')
            if company.company_status: details.append(f'status {company.company_status}')
            if company.date_of_incorporation: details.append(f'incorporated {company.date_of_incorporation}')
            mca_claims.append(Claim(id=f'c{len(claims)+len(mca_claims)+1}',text='MCA master data lists ' + ', '.join(details) + '.',source_id='registry',source_url=company.source_url,snippet=company.snippet[:500]))
        claims.extend(mca_claims)
        from .sources.court import ECOURTS_URL, ECOURTS_REASON
        await emit('source', {'id':rera_id,'status':rera_status,'reason':reason,'url':PORTALS[req.state][0]})
        await emit('source', {'id':'news','status':news_status,'reason':news_reason})
        await emit('source', {'id':'court','status':'not_checked','reason':ECOURTS_REASON,'url':ECOURTS_URL})
        await emit('source', {'id':'registry','status':registry_status,'reason':registry_reason,'url':registry_url})
        await emit('step', {'text':'Assembling the cited report'})
        summary=(f'{rera_label} found {len(projects)} official registered project record(s) for {req.query}. Possession dates and complaint records were not validated, so no risk verdict is assessed.' if rera_ok else f'The {rera_label} check did not return a validated record: {reason or "No projects found."} No verdict.')
        summary += ' Company registry and court checks require manual CAPTCHA completion.'
        summary += ' News search results were not used as claims because analyst validation is not configured.'
        summary_claim_ids=[claim.id for claim in claims if (claim.source_id==rera_id and rera_ok) or (claim.source_id=='registry' and registry_records)]
        report = Report(id=job_id,builder_query=req.query,builder_name=req.query,state=req.state,mode='live',generated_at=now,verdict='unknown',score=0,summary=summary,summary_claim_ids=summary_claim_ids,sources=[Source(id=rera_id,label=rera_label,status=rera_status,reason=reason,checked_at=now,url=PORTALS[req.state][0]),Source(id='news',label='News search',status=news_status,reason=news_reason,checked_at=now),Source(id='court',label='Court records',status='not_checked',reason=ECOURTS_REASON,url=ECOURTS_URL),Source(id='registry',label='Company registry',status=registry_status,reason=registry_reason,checked_at=now,url=registry_url)],claims=claims,projects=projects,complaints=complaints)
    report = score_report(report)
    reports[report.id] = report
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA/f'{report.id}.json').write_text(report.model_dump_json(indent=2))
    await emit('step', {'text':'Report ready'})
    await emit('done', {'report_id':report.id})
    await queue.put(None)

def _as_date(value):
    if not value: return None
    try: return date.fromisoformat(value[:10])
    except (TypeError, ValueError): return None

def _is_rera_url(value: str, state: str = 'Haryana') -> bool:
    try:
        parsed=urlparse(value)
        allowed={'Delhi':{'rera.delhi.gov.in','www.rera.delhi.gov.in'},'Haryana':{'haryanarera.gov.in','www.haryanarera.gov.in','hareraggm.gov.in','www.hareraggm.gov.in'}}
        return parsed.scheme=='https' and parsed.hostname in allowed.get(state,set())
    except ValueError:
        return False
