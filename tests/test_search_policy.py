import json
from copy import deepcopy
from pathlib import Path
import pytest
from sqlalchemy import text
from jobsearch.models import Applicant, SearchPolicy, TierStrategy, JobEvaluation
from jobsearch.scripts.policy_cli import main
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.policy_repository import PolicyRepository
from jobsearch.storage.evaluation_repository import EvaluationRepository


@pytest.fixture
def setup(tmp_path):
    url = f'sqlite:///{tmp_path / "policies.db"}'
    bundle = json.loads(Path('data/search_policy_sample.json').read_text())
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(bundle))
    return url, bundle, path


def test_atomic_import_view_strategy_edit_and_revision(setup, capsys):
    url, bundle, path = setup
    assert main(['--database-url',url,'import','--input',str(path)]) == 0
    capsys.readouterr()
    main(['--database-url',url,'view','--applicant-id','1'])
    saved = json.loads(capsys.readouterr().out)
    assert saved['revision'] == 1 and saved['policy'] == bundle['policy']
    assert [s['tier'] for s in saved['strategies']] == list('ABCD')
    edited = deepcopy(saved['strategies'][1])
    edited['enabled'] = False
    edited['definition']['max_application_minutes'] = 15
    path.write_text(json.dumps(edited))
    command = ['--database-url',url,'strategy-update','--applicant-id','1','--expected-revision','1','--input',str(path)]
    main(command)
    with pytest.raises(ValueError, match='revision conflict'):
        main(command)
    session = get_session(url)
    try:
        assert session.query(Applicant).count() == session.query(SearchPolicy).count() == 1
        assert session.query(TierStrategy).count() == 4
        assert session.get(SearchPolicy,1).revision == 2
        assert not PolicyRepository(session).view(1)['strategies'][1]['enabled']
        assert session.connection().exec_driver_sql('PRAGMA foreign_key_check').all() == []
    finally:
        close_session(session)


@pytest.mark.parametrize('mutation', ['tier','unknown','location','minutes','fabrication'])
def test_invalid_bundle_rolls_back_new_applicant(setup, mutation):
    url, bundle, path = setup
    if mutation == 'tier':
        bundle['strategies'][1]['tier'] = 'A'
    elif mutation == 'unknown':
        bundle['policy']['eligibility']['credentials_complete'] = 'false'
    elif mutation == 'location':
        bundle['policy']['location']['alternatives'][0]['arrangements'] = ['anywhere']
    elif mutation == 'minutes':
        bundle['strategies'][0]['definition']['max_application_minutes'] = True
    else:
        bundle['policy']['automation']['allow_fabrication'] = True
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError):
        main(['--database-url',url,'import','--input',str(path)])
    session = get_session(url)
    try:
        assert session.query(Applicant).count() == 0
        assert session.query(SearchPolicy).count() == session.query(TierStrategy).count() == 0
    finally:
        close_session(session)


def test_reimport_existing_policy_is_idempotent_and_empty_evaluation_is_safe(setup):
    url, bundle, path = setup
    main(['--database-url',url,'import','--input',str(path)])
    del bundle['applicant']
    path.write_text(json.dumps(bundle))
    main(['--database-url',url,'import','--applicant-id','1','--expected-revision','1','--input',str(path)])
    session = get_session(url)
    try:
        assert session.get(SearchPolicy,1).revision == 1
        assert EvaluationRepository(session).evaluate_jobs(1)[0] == []
        assert session.query(JobEvaluation).count() == 0
    finally:
        close_session(session)


def test_migration_preserves_existing_applicant_and_downgrades(setup):
    from alembic.config import Config
    from alembic import command
    url, _, _ = setup
    cfg = Config('alembic.ini')
    cfg.attributes['database_url_override'] = url
    command.upgrade(cfg, '20260917_16')
    session = get_session(url)
    try:
        session.add(Applicant(full_name='Existing example', skills=['SQL']))
        session.commit()
    finally:
        close_session(session)
    run_migrations(url)
    session = get_session(url)
    try:
        assert session.get(Applicant,1).skills == ['SQL']
        assert session.query(SearchPolicy).count() == 0
        assert session.query(TierStrategy).count() == 0
    finally:
        close_session(session)
    command.downgrade(cfg, '20260917_16')
    session = get_session(url)
    try:
        assert session.get(Applicant,1).full_name == 'Existing example'
    finally:
        close_session(session)
