"""Automation must distinguish delivered code from a partial/failed run."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'components/code-agent'))
import pipeline_worker


class FakeAgent:
    cancelled=False
    _outcome='done'
    changed=['hello.py']
    _commands_log=[('python3 hello.py',0)]
    def __init__(self,*args,**kwargs):
        self.ws=args[0]
    def run(self,prompt):return 'Created and tested hello.py'


def test_worker_reports_real_work_and_fails_partial_run(tmp_path):
    lines=[]
    with patch.object(pipeline_worker.core,'CodeAgent',FakeAgent), patch.object(pipeline_worker.core,'LocalLLM'), patch.object(pipeline_worker.core.brief.BriefState,'load',return_value=None):
        assert pipeline_worker.run_task('Synthetic',str(tmp_path),lines.append)==0
        with patch.object(FakeAgent,'_outcome','limit'):
            assert pipeline_worker.run_task('Synthetic',str(tmp_path),lines.append)==1
        with patch.object(FakeAgent,'_commands_log',[('python3 hello.py',1)]):
            assert pipeline_worker.run_task('Synthetic',str(tmp_path),lines.append)==1
    assert json.loads(lines[0])['result']['status']=='completed'


def test_streamed_backend_failure_is_not_a_successful_empty_reply():
    import pytest
    with pytest.raises(pipeline_worker.core.AgentError,match='runtime missing'):
        pipeline_worker.core.read_sse([b'data: {"error":{"message":"runtime missing"}}\n'])


def test_writing_files_without_running_checks_is_incomplete(tmp_path):
    with patch.object(pipeline_worker.core,'CodeAgent',FakeAgent), patch.object(pipeline_worker.core,'LocalLLM'), patch.object(pipeline_worker.core.brief.BriefState,'load',return_value=None), patch.object(FakeAgent,'_commands_log',[]):
        assert pipeline_worker.run_task('Synthetic',str(tmp_path),lambda _:None)==1
