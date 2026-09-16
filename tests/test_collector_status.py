from io import BytesIO

import pytest

from jobsearch.collectors import remotive_collector
from jobsearch.scripts.collectors_cli import main
from jobsearch.scripts.run_remotive_ingestion import run_remotive_ingestion
from jobsearch.storage.source_repository import SourceRepository


def test_status_reports_shared_wait_history_and_skip(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'status.db'}"
    monkeypatch.setattr(remotive_collector, "urlopen", lambda *a, **k: BytesIO(b'{"jobs":[]}'))
    run_remotive_ingestion(database_url=url)
    run_remotive_ingestion(database_url=url)
    repo = SourceRepository(url)
    repo.configure({"name": "other", "adapter_type": "remotive", "enabled": False})
    monkeypatch.setattr(remotive_collector, "urlopen", lambda *a, **k: pytest.fail("Status must not fetch"))
    assert main(["--database-url", url, "status", "--limit", "2"]) == 0
    output = capsys.readouterr().out
    assert "other (remotive): enabled=False" in output
    assert output.count(f"next eligible UTC={repo.get('remotive').next_allowed_at}") >= 2
    assert "Attempt 1: success; HTTP=200" in output
    assert "Run 1: completed; new=0; duplicates=0; invalid=0" in output
    assert "Recent run 2: skipped" in output
    assert main(["--database-url", url, "status", "--name", "other"]) == 0
    assert "Attempt 1" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--database-url", url, "status", "--name", "missing"])


def test_status_unknown_reservation(tmp_path, capsys):
    from jobsearch.collectors.source import REMOTIVE
    from jobsearch.scripts.init_db import run_migrations
    url = f"sqlite:///{tmp_path / 'unknown.db'}"
    run_migrations(url)
    SourceRepository(url).reserve(REMOTIVE)
    assert main(["--database-url", url, "status"]) == 0
    output = capsys.readouterr().out
    assert "unfinished/unknown=1" in output and "reserved (outcome unknown)" in output


@pytest.mark.parametrize("limit", ["0", "101", "-1"])
def test_invalid_limit(limit):
    with pytest.raises(SystemExit) as exc:
        main(["status", "--limit", limit])
    assert exc.value.code == 2
