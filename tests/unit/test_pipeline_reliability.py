"""Synthetic pipeline fixtures only; no personal project prompts."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'components/ai-agent'))
from task_pipeline import TaskPipeline
from antigravity_connection import bind_project, connection_environment


def test_conversation_id_survives_dispatch_copy_and_reload(tmp_path):
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    p.set_base_dir(str(tmp_path/'workspace'))
    p.add('Synthetic first task',project_slug='sample-project')
    def dispatch(task):
        assert Path(task['project']).is_dir()
        task['conversation_id']='synthetic-conversation'
        return True,'STARTED:synthetic-conversation'
    with patch.object(p,'_dispatch',side_effect=dispatch), patch('task_pipeline.is_agent_working',return_value=False), patch('task_pipeline.notify'):
        assert p.execute_next()
    assert json.loads(p.state_file.read_text())[0]['conversation_id']=='synthetic-conversation'
    assert any('prompt accepted' in line for line in p.recent_events())


def test_api_prompt_is_separated_from_flags(tmp_path):
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    result=SimpleNamespace(returncode=0,stdout=json.dumps({'response':{'newConversation':{'conversationId':'sample-id'}}}),stderr='')
    with patch('antigravity_connection.ensure_connection',return_value={}), patch('antigravity_connection.bind_project',return_value={}), patch('task_pipeline.AGENTAPI_BIN',tmp_path), patch('task_pipeline.subprocess.run',return_value=result) as run:
        ok,out=p._dispatch({'agent':'antigravity','prompt':'--not-a-flag','project':str(tmp_path)})
    assert ok and out=='STARTED:sample-id'
    assert run.call_args.args[0][-2:]==['--','--not-a-flag']


def test_project_binding_reuses_exact_workspace_without_extra_grants(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    workspace=tmp_path/'work/sample';workspace.mkdir(parents=True)
    first=bind_project({},workspace)
    second=bind_project({},workspace)
    assert first['ANTIGRAVITY_PROJECT_ID']==second['ANTIGRAVITY_PROJECT_ID']
    data=json.loads(next((tmp_path/'.gemini/config/projects').glob('*.json')).read_text())
    assert data['projectResources']['resources'][0]['gitFolder']['folderUri']==workspace.as_uri()
    assert data['permissionGrants']=={'v2Migrated':True}


def test_explicit_connection_is_preserved(monkeypatch):
    monkeypatch.setenv('ANTIGRAVITY_LS_ADDRESS','127.0.0.1:12345')
    assert connection_environment()['ANTIGRAVITY_LS_ADDRESS']=='127.0.0.1:12345'


def test_slug_cannot_escape_workspace(tmp_path):
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    p.set_base_dir(str(tmp_path/'work'))
    p.add('Synthetic task',project_slug='../../outside')
    assert Path(p.queue[0]['project']).parent==tmp_path/'work'


def test_personal_template_not_bundled(tmp_path,monkeypatch):
    import pipeline_gui
    monkeypatch.setattr(pipeline_gui,'STEPS_25_TEMPLATE_FILE',tmp_path/'private.md')
    monkeypatch.setattr(pipeline_gui,'STEP_PACK_FILE',tmp_path/'step_pack.json')
    assert pipeline_gui.get_steps_25_template()==''
    pipeline_gui.save_steps_25_template('Synthetic local-only instructions')
    assert pipeline_gui.get_steps_25_template()=='Synthetic local-only instructions'
    assert (tmp_path/'private.md').stat().st_mode & 0o777 == 0o600


def test_step_pack_stores_two_to_six(tmp_path,monkeypatch):
    import pipeline_gui
    monkeypatch.setattr(pipeline_gui,'STEPS_25_TEMPLATE_FILE',tmp_path/'private.md')
    monkeypatch.setattr(pipeline_gui,'STEP_PACK_FILE',tmp_path/'step_pack.json')
    assert pipeline_gui.get_step_pack()==[]
    saved=pipeline_gui.save_step_pack(['Alpha tests','Beta docker','Gamma docs'])
    assert saved==['Alpha tests','Beta docker','Gamma docs']
    assert pipeline_gui.get_step_pack()==saved
    assert 'Alpha tests' in pipeline_gui.get_steps_25_template()
    assert pipeline_gui.save_step_pack(['only-one'])==['only-one']


def test_step_groups_serial_auto_add(tmp_path,monkeypatch):
    import pipeline_gui
    monkeypatch.setattr(pipeline_gui,'STEPS_25_TEMPLATE_FILE',tmp_path/'private.md')
    monkeypatch.setattr(pipeline_gui,'STEP_PACK_FILE',tmp_path/'step_pack.json')
    # One pasted block with --- becomes multiple serial steps in a named group.
    pipeline_gui.save_step_groups([
        {'id':'eng','name':'Engineering','steps':['Tests\n---\nDocker\n---\nDocs']},
        {'id':'seo','name':'SEO','steps':['Meta tags','Sitemap']},
    ], default_group_id='eng')
    groups=pipeline_gui.list_step_groups()
    assert [g['name'] for g in groups]==['Engineering','SEO']
    eng=pipeline_gui.get_step_group('eng')
    assert eng['steps']==['Tests','Docker','Docs']
    assert pipeline_gui.get_step_pack()==['Tests','Docker','Docs']
    assert pipeline_gui.get_step_group('seo')['steps']==['Meta tags','Sitemap']


def test_event_callback_and_restart_replay(tmp_path):
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json'); seen=[]
    p.event_callback=seen.append
    p.emit_event('Starting synthetic task')
    assert seen==TaskPipeline(p.state_file,p.context_file).recent_events()
    assert p.state_file.with_suffix('.events.jsonl').stat().st_mode & 0o777 == 0o600


def test_observation_never_dispatches_queued_work(tmp_path):
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    p.add('Synthetic task')
    with patch.object(p,'_dispatch') as dispatch:
        p.observe_tasks()
    dispatch.assert_not_called()
    assert p.list()[0]['status']=='QUEUED'


def test_completion_report_advances_only_matching_successful_attempt(tmp_path):
    from pipeline_completion import prepare
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    p.add('Synthetic first task',project=str(tmp_path/'project'))
    t=p.queue[0];t['status']='RUNNING';prepare(t)
    report=Path(t['completion_report']);report.parent.mkdir(parents=True)
    data={'attempt':'old-attempt','status':'completed','summary':'done','checks':[{'name':'test','passed':True}]}
    report.write_text(json.dumps(data));p._save()
    p.observe_tasks();assert p.list()[0]['status']=='RUNNING'
    data['attempt']=t['completion_token'];data['checks'][0]['passed']=False
    report.write_text(json.dumps(data));p.observe_tasks();assert p.list()[0]['status']=='RUNNING'
    data['checks'][0]['passed']=True;report.write_text(json.dumps(data))
    p.observe_tasks();assert p.list()[0]['status']=='COMPLETED'


def test_failed_report_blocks_dependents(tmp_path):
    from pipeline_completion import prepare
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    p.add('First',project=str(tmp_path/'project'));p.add('Second')
    t=p.queue[0];t['status']='RUNNING';prepare(t)
    path=Path(t['completion_report']);path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'attempt':t['completion_token'],'status':'failed','summary':'Test failed'}));p._save()
    with patch.object(p,'_dispatch') as dispatch:
        p.execute_next()
    dispatch.assert_not_called()
    assert p.list()[0]['status']=='FAILED'


def test_receipt_completion_respects_repository_creation_failure(tmp_path):
    from pipeline_completion import prepare
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    p.add('Synthetic',project=str(tmp_path/'project'),create_repo=True,repo_name='synthetic')
    t=p.queue[0];t['status']='RUNNING';prepare(t)
    path=Path(t['completion_report']);path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'attempt':t['completion_token'],'status':'completed','summary':'done','checks':[{'name':'test','passed':True}]}));p._save()
    with patch('task_pipeline.create_github_repo',return_value=(False,'Synthetic failure')) as create:
        p.observe_tasks()
    create.assert_called_once()
    assert p.list()[0]['status']=='FAILED'
