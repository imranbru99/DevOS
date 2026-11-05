import sys
import threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'components/ai-agent'))
from task_pipeline import TaskPipeline


def test_parallel_projects_and_agent_slots_preserve_step_order(tmp_path):
    p=TaskPipeline(tmp_path/'queue.json', tmp_path/'context.json')
    a=p.add('first',agent='local',project=str(tmp_path/'one'),project_slug='one')
    p.add('second',agent='chatgpt',project=str(tmp_path/'one'),project_slug='one')
    b=p.add('other project',agent='chatgpt',project=str(tmp_path/'two'),project_slug='two')
    p.add('same agent',agent='local',project=str(tmp_path/'three'),project_slug='three')
    gate=threading.Event(); both=threading.Event(); seen=[]
    def dispatch(self,task):
        seen.append(task['id'])
        if len(seen)==2:both.set()
        assert gate.wait(3)
        return True,'verified'
    with patch.object(TaskPipeline,'_dispatch',dispatch),patch('task_pipeline.is_agent_working',return_value=False),patch('task_pipeline.notify'):
        try:
            assert p.execute_parallel_tick()
            assert both.wait(2)
            assert set(seen)=={a,b}
            assert sum(t['status']=='RUNNING' for t in p.list())==2
            assert not p.execute_parallel_tick()
        finally:
            gate.set()
            for thread in p._dispatch_threads:thread.join(3)
        tasks=TaskPipeline(p.state_file,p.context_file).list()
        assert [t['status'] for t in tasks]==['COMPLETED','QUEUED','COMPLETED','QUEUED']


def test_failed_project_does_not_block_another_and_aliases_share_slot(tmp_path):
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    a=p.add('failed',agent='local',project=str(tmp_path/'one'))
    p.update_task(a,{'status':'FAILED'})
    p.add('blocked successor',agent='chatgpt',project=str(tmp_path/'one'))
    b=p.add('ready',agent='chatgpt',project=str(tmp_path/'two'))
    with patch('task_pipeline.is_agent_working',return_value=False),patch('task_pipeline.notify'):
        assert p._claim_next(parallel=True)['id']==b
        p.add('alias',agent='codex',project=str(tmp_path/'three'))
        assert not p._claim_next(parallel=True)


def test_kde_missing_api_never_launches_or_borrows_primary_connection():
    import antigravity_connection as connection
    import pytest
    with patch.object(connection,'connection_environment',return_value=None) as env, patch.object(connection.subprocess,'Popen') as launch:
        with pytest.raises(RuntimeError,match='independent prompt API'):
            connection.ensure_connection('/tmp',lambda _:None,profile='antigravity-kde')
        env.assert_called_once_with('antigravity-kde')
        launch.assert_not_called()


def test_kde_configuration_cannot_inherit_primary_environment(tmp_path,monkeypatch):
    import antigravity_connection as connection
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    monkeypatch.setenv('ANTIGRAVITY_LS_ADDRESS','primary:1234')
    monkeypatch.setenv('ANTIGRAVITY_CSRF_TOKEN','synthetic-test-value')
    with patch.object(connection.Path,'iterdir',return_value=iter([])):
        assert connection.connection_environment('antigravity-kde') is None
        assert connection.connection_environment()['ANTIGRAVITY_LS_ADDRESS']=='primary:1234'
