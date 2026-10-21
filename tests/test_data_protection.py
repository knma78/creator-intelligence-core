from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from infrastructure.atomic_io import atomic_write_json
from infrastructure.data_cleanup import cleanup_plan, quarantine_indexes, restore_quarantine
from infrastructure.data_inventory import inventory
from infrastructure.data_snapshots import create_snapshot, list_snapshots, restore_drill, safe_child, verify_snapshot
from infrastructure.file_lock import file_lock
from infrastructure.rule_versions import content_fingerprint, evidence_binding, refresh_observation_hashes, resolve_review, review_token, version_rule
from webapp.knowledge_reviews import knowledge_rules, record_rule_review


@pytest.fixture
def settings(tmp_path):
    return SimpleNamespace(
        base_dir=tmp_path, output_dir=tmp_path / 'output', cache_dir=tmp_path / 'cache',
        video_production_dir=tmp_path / 'output/video_production',
        job_database_path=tmp_path / 'cache/jobs/jobs.sqlite3',
        creator_progress_database_path=tmp_path / 'state/creator_progress.sqlite3',
        analytics_database_path=tmp_path / 'cache/analytics/content_research.duckdb',
    )


def write(path, data=b'content'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_snapshot_sqlite_wal_and_isolated_restore(settings):
    atomic_write_json(settings.output_dir / 'evidence.json', {'source': 'v1'})
    write(settings.cache_dir / 'video.mp4.part')
    write(settings.cache_dir / 'models/model.bin')
    write(settings.cache_dir / 'cookies.txt', b'secret')
    write(settings.video_production_dir / 'narration.wav')
    database = settings.creator_progress_database_path
    database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE progress (video TEXT)')
        db.execute("INSERT INTO progress VALUES ('learned')")
        db.commit()
        result = create_snapshot(settings)
    assert result['verified']
    snapshot = Path(result['snapshot'])
    copied = snapshot / 'files/state/creator_progress.sqlite3'
    with closing(sqlite3.connect(copied)) as db:
        assert db.execute('SELECT video FROM progress').fetchone() == ('learned',)
    assert (snapshot / 'files/output/video_production/narration.wav').exists()
    assert not (snapshot / 'files/cache/video.mp4.part').exists()
    assert not (snapshot / 'files/cache/models/model.bin').exists()
    assert not (snapshot / 'files/cache/cookies.txt').exists()
    assert result['omitted_count'] == 2
    before = (settings.output_dir / 'evidence.json').read_bytes()
    restored = restore_drill(settings, result['snapshot_id'])
    assert restored['live_data_modified'] is False
    assert restored['path_rebinding_required'] is True
    assert (Path(restored['restored_to']) / 'output/evidence.json').read_bytes() == before
    assert (settings.output_dir / 'evidence.json').read_bytes() == before
    write(snapshot / 'files/output/evidence.json', b'changed')
    with pytest.raises(ValueError, match='校验失败'):
        verify_snapshot(snapshot)


def test_optional_media_and_models(settings):
    write(settings.cache_dir / 'clip.mp4')
    write(settings.cache_dir / 'models/model.bin')
    result = create_snapshot(settings, include_media=True, include_models=True)
    assert result['file_count'] == 2 and result['omitted_count'] == 0


def test_malformed_existing_json_is_preserved_with_explicit_warning(settings):
    raw = b'{"test": 1} extra data'
    write(settings.output_dir / 'invalid.json', raw)
    result = create_snapshot(settings)
    assert result['verified'] and result['format_warning_count'] == 1
    assert result['format_warnings'][0]['key'] == 'output/invalid.json'
    assert (Path(result['snapshot']) / 'files/output/invalid.json').read_bytes() == raw


def test_duckdb_backup_preserves_schema_and_data(settings):
    duckdb = pytest.importorskip('duckdb')
    database = settings.analytics_database_path
    database.parent.mkdir(parents=True)
    with duckdb.connect(str(database)) as db:
        db.execute('CREATE TABLE evidence (id INTEGER PRIMARY KEY, label VARCHAR)')
        db.execute("INSERT INTO evidence VALUES (1, 'source')")
        db.execute('CREATE VIEW source_view AS SELECT * FROM evidence')
        db.execute('CREATE SEQUENCE next_id START 2')
    original = database.read_bytes()
    result = create_snapshot(settings)
    copied = Path(result['snapshot']) / 'files/cache/analytics/content_research.duckdb'
    with duckdb.connect(str(copied), read_only=True) as db:
        assert db.execute('SELECT * FROM source_view').fetchall() == [(1, 'source')]
        assert db.execute('SELECT sequence_name FROM duckdb_sequences()').fetchone() == ('next_id',)
    assert database.read_bytes() == original


def test_changed_source_or_cancel_never_publishes_snapshot(settings):
    source = write(settings.output_dir / 'evidence.txt')
    with pytest.raises(RuntimeError, match='数据集合'):
        create_snapshot(settings, progress=lambda *_: source.write_bytes(b'new content'))
    assert list_snapshots(settings) == []
    def cancel(*_):
        raise InterruptedError('cancel')
    with pytest.raises(InterruptedError):
        create_snapshot(settings, progress=cancel)
    assert list_snapshots(settings) == []
    assert source.exists()


@pytest.mark.parametrize('key', ['../outside', '/absolute', 'C:/outside', 'a\\b', 'a//b', './file'])
def test_restore_paths_are_confined(tmp_path, key):
    with pytest.raises(ValueError):
        safe_child(tmp_path, key)


def test_inventory_rejects_linked_root_before_resolving(settings):
    settings.output_dir.mkdir()
    with patch('infrastructure.data_inventory.linked', side_effect=lambda p: p == settings.output_dir):
        with pytest.raises(ValueError, match='链接'):
            inventory(settings)


def prepare_index(settings):
    atomic_write_json(settings.output_dir / 'creator_knowledge_base/rules/rule_library.json',
                      {'rag_index': {'documents': [{'id': 'R-001'}]}})
    index = settings.cache_dir / 'creator_knowledge_base/rule_index.json'
    atomic_write_json(index, {'documents': [{'id': 'R-001'}]})
    result = create_snapshot(settings)
    return index, result['snapshot_id']


def test_quarantine_undo_and_stale_plan(settings):
    index, snapshot_id = prepare_index(settings)
    plan = cleanup_plan(settings, snapshot_id)
    assert len(plan['candidates']) == 1
    with pytest.raises(ValueError, match='清单已变化'):
        quarantine_indexes(settings, snapshot_id, 'stale')
    result = quarantine_indexes(settings, snapshot_id, plan['plan_token'])
    assert not index.exists() and result['disk_bytes_freed'] == 0
    original = b'new index'
    write(index, original)
    with pytest.raises(ValueError, match='不会覆盖'):
        restore_quarantine(settings, result['quarantine_id'])
    assert index.read_bytes() == original
    index.unlink()  # synthetic test fixture only
    assert restore_quarantine(settings, result['quarantine_id'])['restored_count'] == 1
    assert index.exists()
    assert restore_quarantine(settings, result['quarantine_id'])['restored_count'] == 0


def test_quarantine_reconciles_crash_before_journal_update(settings):
    index, snapshot_id = prepare_index(settings)
    plan = cleanup_plan(settings, snapshot_id)
    result = quarantine_indexes(settings, snapshot_id, plan['plan_token'])
    manifest = Path(result['manifest'])
    journal = json.loads(manifest.read_text(encoding='utf-8'))
    journal['files'][0]['state'] = 'pending'
    atomic_write_json(manifest, journal)
    assert restore_quarantine(settings, result['quarantine_id'])['restored_count'] == 1
    journal['files'][0]['state'] = 'quarantined'
    atomic_write_json(manifest, journal)
    assert restore_quarantine(settings, result['quarantine_id'])['restored_count'] == 0
    assert json.loads(manifest.read_text(encoding='utf-8'))['files'][0]['state'] == 'restored'


def test_missing_rebuild_source_is_blocked(settings):
    _, snapshot_id = prepare_index(settings)
    (settings.output_dir / 'creator_knowledge_base/rules/rule_library.json').unlink()
    plan = cleanup_plan(settings, snapshot_id)
    assert not plan['candidates'] and len(plan['blocked']) == 1


def test_shared_exclusive_lock_and_cancellation(tmp_path):
    lock = tmp_path / 'maintenance.lock'
    with file_lock(lock, exclusive=False):
        with file_lock(lock, exclusive=False, timeout=.05):
            pass
        with pytest.raises(TimeoutError):
            with file_lock(lock, timeout=.05):
                pytest.fail('exclusive must not overlap a shared reader')
        def cancel():
            raise InterruptedError('cancel')
        with pytest.raises(InterruptedError):
            with file_lock(lock, check=cancel):
                pass
    with pytest.raises(RuntimeError):
        with file_lock(lock):
            raise RuntimeError('exit')
    with file_lock(lock, timeout=.05):
        pass


def sample_rule():
    return {'rule_id': 'R-001', 'name': 'Test', 'definition': 'An opening', 'layer': 'opening',
            'condition': ['conflict'], 'Evidence': {'video_ids': ['v1'], 'observation_ids': ['o1'],
            'evidence_type': 'direct_pattern_observation'}, 'Counter Examples': []}


def approval(rule):
    return {'approved': True, 'status': 'validated', 'reviewer': 'test', 'reviewed_at': 'now',
            'content_fingerprint': content_fingerprint(rule), 'evidence_binding': evidence_binding(rule)}


def test_review_versions_evidence_and_legacy():
    original = sample_rule()
    decision = approval(original)
    first = version_rule(deepcopy(original), {}, decision)
    assert first['content_revision'] == 1 and first['human_reviewed']
    expanded = deepcopy(original)
    expanded['Evidence']['video_ids'].append('v2')
    expanded['generated_at'] = 'later'
    assert version_rule(expanded, first, decision)['status'] == 'validated'
    assert expanded['content_revision'] == 1
    changed = deepcopy(original)
    changed['condition'] = ['different']
    result = version_rule(changed, first, decision)
    assert result['content_revision'] == 2 and result['status'] == 'under_review'
    assert not result['human_reviewed']
    for changed in [dict(original, Evidence={}), dict(original, **{'Counter Examples': ['counterexample']})]:
        assert resolve_review(changed, decision)[1]
    assert resolve_review(original, {'approved': True})[0]['status'] == 'under_review'
    assert resolve_review(original, {'approved': False, 'reviewer': ''}) == ({}, '')
    assert resolve_review(dict(original, status='validated'), {})[0]['status'] == 'under_review'


def test_same_evidence_id_changed_content_requires_review():
    rule = sample_rule()
    rule['Evidence']['examples'] = [{'video_id': 'v1', 'matched_signal': 'question', 'view_count': 1}]
    decision = approval(rule)
    token = review_token(rule)
    rule['Evidence']['examples'][0]['view_count'] = 20
    assert not resolve_review(rule, decision)[1]
    rule['Evidence']['examples'][0]['matched_signal'] = 'not a question'
    assert resolve_review(rule, decision)[0]['status'] == 'under_review'
    assert review_token(rule) != token


def test_all_observations_not_just_representatives_are_bound():
    rule = sample_rule()
    observation = {'observation_id': 'o1', 'detected_signal': 'question', 'location': {'time_range': '00:01-00:03'}}
    library = {'rules': [rule], 'observation_library': [observation]}
    refresh_observation_hashes(library)
    decision = approval(rule)
    observation['location']['time_range'] = '00:12-00:15'
    refresh_observation_hashes(library)
    assert resolve_review(rule, decision)[1]
    legacy = approval(rule)
    legacy['evidence_binding'].pop('binding_version')
    assert resolve_review(rule, legacy)[1]


def test_review_history_stale_token_and_ui(settings):
    rule = sample_rule()
    library = settings.output_dir / 'creator_knowledge_base/rules/rule_library.json'
    atomic_write_json(library, {'rules': [rule]})
    payload = {'rule_id': 'R-001', 'status': 'validated', 'reviewer': 'human', 'review_token': review_token(rule)}
    record_rule_review(payload, settings)
    assert knowledge_rules(settings)['rules'][0]['human_reviewed']
    record_rule_review(dict(payload, status='rejected'), settings)
    history = json.loads(library.with_name('rule_reviews.json').read_text(encoding='utf-8'))['history']
    assert len(history) == 2 and history[0]['decision']['status'] == 'validated'
    rule['definition'] = 'Changed definition'
    atomic_write_json(library, {'rules': [rule]})
    with pytest.raises(ValueError, match='版本已变化'):
        record_rule_review(payload, settings)
    listed = knowledge_rules(settings)['rules'][0]
    assert listed['status'] == 'under_review' and not listed['human_reviewed']
    assert listed['review_required_reason']


def test_rebuild_does_not_overwrite_unreadable_previous_library(settings):
    from exporter.rule_library import build_rule_library
    library = write(settings.output_dir / 'creator_knowledge_base/rules/rule_library.json', b'broken JSON')
    with pytest.raises(ValueError):
        build_rule_library({}, output_root=settings.output_dir, cache_root=settings.cache_dir)
    assert library.read_bytes() == b'broken JSON'


def test_planner_downgrades_legacy_approval(settings):
    from intelligence.capability_planner import build_capability_plan
    rule = sample_rule()
    rule.update(status='validated', review={'approved': True, 'status': 'validated'})
    path = settings.output_dir / 'rules.json'
    atomic_write_json(path, {'rules': [rule]})
    plan = build_capability_plan('Test conflict', rule_library_path=path)
    selected = plan['selections'][0]['primary']
    assert selected['status'] == 'under_review'
    assert selected['review_required_reason']


def test_data_job_backup_verify_restore_and_cancel(settings):
    from config import Settings
    from webapp.server import AppState, _run_job
    state = AppState(Settings(base_dir=settings.base_dir, output_dir=settings.output_dir,
                              cache_dir=settings.cache_dir, logs_dir=settings.base_dir / 'logs'))
    try:
        atomic_write_json(settings.output_dir / 'evidence.json', {'source': 'v1'})
        job = state.submit({'mode': 'data_maintenance', 'operation': 'backup'})
        _run_job(state, job['id'])
        finished = state.jobs.get(job['id'])
        assert finished['status'] == 'done', finished.get('error')
        snapshot_id = finished['result']['details']['snapshot_id']
        for operation in ('verify', 'restore-drill', 'cleanup-plan'):
            job = state.submit({'mode': 'data_maintenance', 'operation': operation, 'snapshot_id': snapshot_id})
            _run_job(state, job['id'])
            finished = state.jobs.get(job['id'])
            assert finished['status'] == 'done', finished.get('error')
        job = state.submit({'mode': 'data_maintenance', 'operation': 'backup'})
        state.request_cancel(job['id'])
        _run_job(state, job['id'])
        assert state.jobs.get(job['id'])['status'] == 'cancelled'
    finally:
        state.close()


def test_data_http_submit_status_and_validation(settings):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import Request, urlopen
    from config import Settings
    from webapp.server import AppState, create_handler
    state = AppState(Settings(base_dir=settings.base_dir, output_dir=settings.output_dir,
                              cache_dir=settings.cache_dir, logs_dir=settings.base_dir / 'logs'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), create_handler(state))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base + '/api/data/status', timeout=5) as response:
            assert json.load(response)['snapshots'] == []
        request = Request(base + '/api/data/backup', data=b'{"include_media":"false"}',
                          headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(request, timeout=5) as response:
            assert response.status == 202
            job = json.load(response)
            assert job['payload']['include_media'] is False
            assert job['payload']['mode'] == 'data_maintenance'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        state.close()
