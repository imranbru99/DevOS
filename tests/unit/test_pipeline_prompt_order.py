import sys
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'components/ai-agent'))
from task_pipeline import TaskPipeline, get_grouped_projects


def test_append_stays_in_project_before_next_project_and_preserves_long_prompt(tmp_path):
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    first=p.add('First',project_slug='one',project=str(tmp_path/'custom'))
    next_id=p.add('Other',project_slug='two')
    text='Master huge prompt\n\n---\n'+'long text '*6000
    added=p.append_project_prompt('one',text)
    assert [t['id'] for t in p.list()]==[first,added,next_id]
    assert p.list()[1]['project']==str(tmp_path/'custom')
    assert p.list()[1]['prompt']==text
    assert len(get_grouped_projects(p.list()))==2
    p.move_project_prompt(added,-1)
    reloaded=TaskPipeline(p.state_file,p.context_file)
    assert [t['id'] for t in reloaded.list()]==[added,first,next_id]
    assert reloaded.list()[0]['prompt']==text


def test_reorder_cannot_cross_a_started_step(tmp_path):
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    first=p.add('First',project_slug='one')
    second=p.append_project_prompt('one','Second')
    p.update_task(first,{'status':'RUNNING'})
    with pytest.raises(ValueError,match='unstarted'):
        p.move_project_prompt(second,-1)
    assert [t['id'] for t in p.list()]==[first,second]


def test_card_compact_rows_add_and_move_callbacks(tmp_path):
    from PyQt5 import QtWidgets
    import pipeline_gui as gui
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json')
    p.add('one two three four five six '+('more '*5000),project_slug='sample')
    second=p.append_project_prompt('sample','Second prompt')
    calls=[]
    with patch.object(gui,'discover_agents',return_value={}):
        card=gui.ProjectPipelineCard(get_grouped_projects(p.list())[0],on_add_prompt=lambda slug:calls.append(slug),on_move_prompt=lambda tid,d:calls.append((tid,d)))
    assert card.show_all_mode and len(card.step_rows)==2
    assert card.step_rows[0].findChild(QtWidgets.QLabel,'prompt_preview').text()=='one two three four five …'
    assert not card.step_rows[0].findChildren(QtWidgets.QTextEdit)
    card.findChild(QtWidgets.QPushButton,'add_project_prompt').click()
    next(b for b in card.step_rows[1].findChildren(QtWidgets.QPushButton) if b.text()=='↑').click()
    assert calls==['sample',(second,-1)]
    card.close()


def test_add_dialog_adds_one_whole_prompt(tmp_path):
    from PyQt5 import QtWidgets
    import pipeline_gui as gui
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    p=TaskPipeline(tmp_path/'queue.json',tmp_path/'context.json');p.add('First',project_slug='sample')
    window=QtWidgets.QWidget();window.pipeline=p;window.busy=lambda:False;window.refresh_queue=lambda:None
    def accept(dialog):
        dialog.findChild(QtWidgets.QPlainTextEdit).setPlainText('Full prompt\n---\nStill same prompt')
        return QtWidgets.QDialog.Accepted
    with patch.object(gui.QtWidgets.QDialog,'exec_',accept),patch.object(gui,'discover_agents',return_value={'antigravity':{'name':'Antigravity'}}):
        gui.PipelineWindow.add_prompt_to_project(window,'sample')
    assert len(p.list())==2 and len(get_grouped_projects(p.list()))==1
    assert p.list()[1]['prompt']=='Full prompt\n---\nStill same prompt'
    assert not window.editing_queue
    window.close()


def test_draft_submission_pagination_and_clear_logs(tmp_path):
    from PyQt5 import QtWidgets
    import pipeline_gui as gui
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    p = TaskPipeline(tmp_path/'queue.json', tmp_path/'context.json')
    p.set_base_dir(str(tmp_path/'projects'))
    with patch.object(gui, 'TaskPipeline', return_value=p), patch.object(gui, 'discover_agents', return_value={}), patch.object(gui, 'detect_current_project', return_value=(None,None,None)), patch.object(gui, 'notify'):
        w = gui.PipelineWindow()
        w.timer.stop(); w.runner_timer.stop()
        first = 'one two three four five six\n---\n' + ('large '*6000).strip()
        w.next_prompt_input.setPlainText(first); w.stage_prompt()
        w.next_prompt_input.setPlainText('Second prompt'); w.stage_prompt()
        assert p.list() == []
        w.move_draft_prompt(-1)
        assert w.draft_prompts == ['Second prompt', first]
        w.next_title_input.setText('Sample'); w.add_next_project_tasks()
        assert [t['prompt'] for t in p.list()] == ['Second prompt', first]
        assert len(get_grouped_projects(p.list())) == 1
        for name in ['Two', 'Three']:
            w.next_title_input.setText(name)
            w.next_prompt_input.setPlainText(name+' prompt'); w.add_next_project_tasks()
        assert w.project_page == 2 and not w.next_project_btn.isEnabled()
        w.change_project_page(-1)
        assert w.project_page_label.text() == 'Project 2 of 3'
        assert w.task_list_layout.count() == 2
        p.emit_event('Test activity')
        snapshot = p.list()
        w.clear_logs()
        assert p.recent_events() == [] and p.list() == snapshot
        p.emit_event('Test activity')
        assert len(p.recent_events()) == 1
        w.resize(1366,720); w.show(); app.processEvents()
        w.grab().save('/tmp/devos-pipeline-layout.png')
        w.close()
