import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch
import pytest

AI_CORE=Path(__file__).resolve().parents[2]/'components/ai-core'
sys.path.insert(0,str(AI_CORE))
spec=importlib.util.spec_from_file_location('runtime_test_server',AI_CORE/'server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)


def test_missing_coding_model_is_error_not_setup_chat():
    with patch.object(server.HardwareDetector,'evaluate_tier',return_value={'tier':'Basic','ram_gb':4}):
        engine=server.DevOSAIEngine()
    with patch.object(engine,'_find_model',return_value=None):
        with pytest.raises(server.ModelUnavailable):
            engine.generate_chat_response([{'role':'user','content':'Write code'}],model='devos-ai-code')
        with pytest.raises(server.ModelUnavailable):
            list(engine.stream_chat([{'role':'user','content':'Write code'}],model='devos-ai-code'))
