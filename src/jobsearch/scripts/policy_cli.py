"""Configure policies and tier strategies; does not evaluate jobs or contact APIs."""
import argparse
import json
from pathlib import Path
from sqlalchemy import text
from jobsearch.config.settings import get_settings
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.policy_repository import PolicyRepository, exact


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', default=get_settings().database_url)
    commands = parser.add_subparsers(dest='command', required=True)
    imp = commands.add_parser('import', help='Create applicant with policy, or replace an existing policy atomically')
    imp.add_argument('--input', type=Path, required=True)
    imp.add_argument('--applicant-id', type=int)
    imp.add_argument('--expected-revision', type=int)
    view = commands.add_parser('view')
    view.add_argument('--applicant-id', type=int, required=True)
    update = commands.add_parser('strategy-update', help='Replace one strategy; input includes tier/name/enabled/definition')
    update.add_argument('--applicant-id', type=int, required=True)
    update.add_argument('--expected-revision', type=int, required=True)
    update.add_argument('--input', type=Path, required=True)
    args = parser.parse_args(argv)
    run_migrations(args.database_url)
    session = get_session(args.database_url)
    try:
        repo = PolicyRepository(session)
        if args.command == 'view':
            print(json.dumps(repo.view(args.applicant_id), indent=2))
            return 0
        session.execute(text('BEGIN IMMEDIATE'))
        payload = json.loads(args.input.read_text(encoding='utf-8-sig'))
        if args.command == 'import':
            if args.applicant_id is None:
                exact(payload, ('applicant','policy','strategies'), 'New applicant bundle')
                applicant = ApplicantRepository(session).create_from_payload(payload['applicant'])
                applicant_id = applicant.id
            else:
                exact(payload, ('policy','strategies'), 'Existing applicant policy bundle')
                applicant_id = args.applicant_id
            saved = repo.save(applicant_id, payload['policy'], payload['strategies'], args.expected_revision)
        else:
            bundle = repo.view(args.applicant_id)
            if not isinstance(payload, dict) or payload.get('tier') not in ('A','B','C','D'):
                raise ValueError('Strategy requires tier A-D')
            strategies = [payload if s['tier'] == payload['tier'] else s for s in bundle['strategies']]
            saved = repo.save(args.applicant_id, bundle['policy'], strategies, args.expected_revision)
        session.commit()
        print(f'Saved applicant={saved.applicant_id} policy_revision={saved.revision}; four strategies; evaluation not enabled')
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        close_session(session)


if __name__ == '__main__':
    raise SystemExit(main())
