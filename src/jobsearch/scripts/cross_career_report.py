"""Evaluate database-backed profiles; report relevance separately from eligibility."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from jobsearch.evaluation.parser_profiles import load_profile
from jobsearch.evaluation.job_facts import parse_as_of
from jobsearch.evaluation.qualification import HARD_CHECKS
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.evaluation_repository import EvaluationRepository
from jobsearch.scripts.init_db import run_migrations


def build_report(session, applicant_ids, parser_profile, as_of):
    report = dict(as_of=as_of.isoformat(), profiles=[])
    for identifier in applicant_ids:
        results, summary = EvaluationRepository(session).evaluate_jobs(identifier, as_of=as_of, parser_profile=parser_profile)
        groups = {}
        records = []
        for result in results:
            snapshot = result.input_context
            source = snapshot['job']['source']
            group = groups.setdefault(source, Counter())
            gate = next(r for r in result.reasons if r['check']=='qualification_gate')
            assessment = gate['assessment']
            sections = assessment.get('extraction', {}).get('section_analysis', {}).get('sections', [])
            clause_kinds = Counter(c['kind'] for section in sections for c in section['clauses'])
            paths = [dict(kind=p['kind'], grade=p['grade'], status=p['comparison']['status'])
                     for p in assessment.get('path_assessments', [])]
            relevance = assessment.get('role_relevance', {})
            overall = assessment.get('overall_qualification')
            overall_summary = None if overall is None else dict(status=overall['status'],
                coverage_complete=overall['coverage_complete'], blockers=overall['blockers'],
                grades=[dict(grade=p['grade'], status=p['comparison']['status']) for p in overall['grades']])
            group['jobs'] += 1
            group[result.queue_state] += 1
            if relevance.get('supported'):
                group['supported_role_signal'] += 1
                if result.queue_state == 'unresolved': group['relevant_but_held'] += 1
            group['requirements_' + assessment['status']] += 1
            if sections:
                group['jobs_with_qualification_sections'] += 1
                group['qualification_clause_observations'] += sum(clause_kinds.values())
            for path in paths:
                group[path['status'] + '_requirement_components'] += 1
            records.append(dict(job_id=result.job_id,source=source,title=snapshot['job']['title'],
                queue_state=result.queue_state,qualification=assessment['status'],
                qualification_clause_kinds=dict(clause_kinds),
                qualification_paths=paths,
                overall_qualification=overall_summary,
                source_conditions=assessment.get('source_conditions', []),
                readiness_blockers=[dict(check=r['check'],outcome=r['outcome'],message=r['message'])
                    for r in result.reasons if r['check'] in HARD_CHECKS and r['outcome'] in {'review','reject'}],
                role_relevance=bool(relevance.get('supported')),tier=result.tier,
                reasons=[dict(check=r['check'],outcome=r['outcome'],message=r['message']) for r in result.reasons]))
        report['profiles'].append(dict(applicant_id=identifier,groups={k:dict(v) for k,v in groups.items()},
                                      evaluation_summary=summary,records=records))
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url',required=True)
    parser.add_argument('--applicant-id',type=int,action='append',required=True)
    parser.add_argument('--parser-profile',required=True)
    parser.add_argument('--as-of',type=parse_as_of)
    parser.add_argument('--output',type=Path,required=True,help='New private JSON report path')
    parser.add_argument('--expectations',type=Path,help='Optional predeclared acceptance cases for this database')
    args=parser.parse_args(argv)
    if args.output.exists(): parser.error('Output exists; choose a new path')
    profile=load_profile(args.parser_profile)
    run_migrations(args.database_url)
    session=get_session(args.database_url)
    try:
        report=build_report(session,args.applicant_id,profile,args.as_of or datetime.now(timezone.utc))
        if args.expectations:
            cases=json.loads(args.expectations.read_text(encoding='utf-8'))
            checked=[]
            for case in cases['cases']:
                person=next(p for p in report['profiles'] if p['applicant_id']==case['applicant_id'])
                row=next(r for r in person['records'] if r['job_id']==case['job_id'])
                actual={field:row[field] for field in case['expected']}
                checked.append(dict(applicant_id=case['applicant_id'],job_id=case['job_id'],
                    expected=case['expected'],actual=actual,passed=actual==case['expected'],reason=case['reason']))
            report['acceptance']=checked
            if not all(c['passed'] for c in checked):
                raise ValueError('Acceptance case failed; evaluation batch rolled back')
        with args.output.open('x',encoding='utf-8') as handle: json.dump(report,handle,indent=2)
        session.commit()
        for row in report['profiles']: print(json.dumps({k:v for k,v in row.items() if k!='records'}))
    except Exception:
        session.rollback()
        raise
    finally: close_session(session)
    return 0


if __name__=='__main__': raise SystemExit(main())
