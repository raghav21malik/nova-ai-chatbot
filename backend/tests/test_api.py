import importlib
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv('LLM_API_KEYS', 'test-a,test-b')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path}/test.db')
    monkeypatch.setenv('ENABLE_FAILURE_SIMULATION', 'true')
    import app.main as main
    main = importlib.reload(main)
    class FakeCache:
        def __init__(self): self.data = {}
        def get_cache(self, key): return self.data.get(key)
        def set_cache(self, key, value): self.data[key] = value
    main.CACHE.cache = FakeCache()
    async def fake_completion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Answer to: ' + kwargs['messages'][-1]['content']))], usage=SimpleNamespace(prompt_tokens=24, completion_tokens=7))
    monkeypatch.setattr(main.litellm, 'acompletion', fake_completion)
    with TestClient(main.app) as client:
        yield client, main

def test_health(env):
    client, _ = env
    assert client.get('/health').json() == {'status':'ok','keys_configured':2,'cache_enabled':True}

def test_validation(env):
    client, _ = env
    for body in ({'session_id':'a','message':'  '}, {'session_id':'','message':'x'}, {'session_id':'a','message':'x'*4001}, {}):
        assert client.post('/chat', json=body).status_code == 422

def test_cache_across_sessions(env):
    client, _ = env
    first = client.post('/chat', json={'session_id':'a','message':'Hello'}).json()
    second = client.post('/chat', json={'session_id':'b','message':'Hello'}).json()
    assert first['metadata']['resolution_source'] == 'LIVE_INFERENCE'
    assert second['metadata']['resolution_source'] == 'LLM_CACHE'
    assert second['reply'] == first['reply']
    assert second['metadata']['key_id'] is None
    assert second['metadata']['input_tokens'] == first['metadata']['input_tokens']
    assert client.post('/chat', json={'session_id':'c','message':'Different'}).json()['metadata']['resolution_source'] == 'LIVE_INFERENCE'

def test_history_and_multiturn(env):
    client, _ = env
    client.post('/chat', json={'session_id':'a','message':'My name is Sam'})
    client.post('/chat', json={'session_id':'a','message':'What is my name?'})
    history = client.get('/sessions/a/messages').json()['messages']
    assert [m['role'] for m in history] == ['user','assistant','user','assistant']
    assert client.get('/sessions/unknown/messages').status_code == 404

def test_failover_and_all_failed(env):
    client, _ = env
    result = client.post('/chat', json={'session_id':'a','message':'One'}, headers={'X-Simulate-Failure':'key_1=429'})
    assert result.status_code == 200
    assert result.json()['metadata']['key_id'] == 'key_2'
    assert result.json()['metadata']['fallback_attempts'] == 1
    failed = client.post('/chat', json={'session_id':'new','message':'Fail'}, headers={'X-Simulate-Failure':'*=429'})
    assert failed.status_code == 503
    assert failed.json() == {'detail':'all providers unavailable'}
    assert client.get('/sessions/new/messages').status_code == 404

def test_system_prompt_changes_cache_key(env):
    client, _ = env
    a = client.post('/chat', json={'session_id':'a','message':'Hi','system_prompt':'Be brief'}).json()
    b = client.post('/chat', json={'session_id':'b','message':'Hi','system_prompt':'Be detailed'}).json()
    assert a['metadata']['resolution_source'] == b['metadata']['resolution_source'] == 'LIVE_INFERENCE'
