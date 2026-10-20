from .models import Report, Flag

def score_report(report: Report) -> Report:
    score, flags = 0, []
    for project in report.projects:
        if project.revisions is None:
            continue
        if project.revisions >= 3:
            score += 3; flags.append(Flag(label=f'{project.name}: {project.revisions} possession date revisions', severity='high', claim_ids=project.claim_ids))
        elif project.revisions:
            score += 1; flags.append(Flag(label=f'{project.name}: {project.revisions} possession date revision(s)', severity='medium', claim_ids=project.claim_ids))
    pending = [c for c in report.complaints if c.status == 'pending']
    if pending:
        score += min(4, len(pending)); flags.append(Flag(label=f'{len(pending)} pending complaint(s)', severity='medium', claim_ids=[c.claim_id for c in pending]))
    if len(report.complaints) >= 4 and len(pending) / len(report.complaints) > .5:
        score += 2; flags.append(Flag(label='More than half of listed complaints are pending', severity='high', claim_ids=[c.claim_id for c in pending]))
    adverse = [n for n in report.news if n.tag in ('fraud','litigation')]
    delays = [n for n in report.news if n.tag == 'delay']
    if adverse:
        score += min(4, len(adverse)*2); flags.append(Flag(label=f'{len(adverse)} news item(s) tagged litigation or fraud by source classification', severity='high', claim_ids=[n.claim_id for n in adverse]))
    if delays:
        score += min(2, len(delays)); flags.append(Flag(label=f'{len(delays)} news item(s) tagged delay', severity='medium', claim_ids=[n.claim_id for n in delays]))
    report.score, report.flags = score, flags
    # A verdict is only meaningful when the RERA source for this report's
    # state returned at least one validated project. This handles both state
    # portals and prevents sparse saved examples from looking like clean checks.
    rera_id = 'rera_dl' if report.state == 'Delhi' else 'rera_hr'
    rera = next((source for source in report.sources if source.id == rera_id), None)
    assessed = bool(rera and rera.status == 'ok' and report.projects)
    report.verdict = ('low' if score <= 2 else 'medium' if score <= 5 else 'high') if assessed else 'unknown'
    return report
