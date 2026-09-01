from core.local_ai_router import LocalAIRouter


class Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")
    def json(self):
        return self._payload


def test_router_discovers_installed_roles(monkeypatch):
    def get(url, **kwargs):
        return Response({"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3.1:latest"}, {"name": "nomic-embed-text:latest"}]})
    monkeypatch.setattr("core.local_ai_router.requests.get", get)
    router = LocalAIRouter(timeout=1)
    state = router.discover_models()
    assert state.coder == "qwen2.5-coder:7b"
    assert state.embedder == "nomic-embed-text:latest"
    assert state.responder == "llama3.1:latest"


def test_router_extracts_strict_json(monkeypatch):
    monkeypatch.setattr("core.local_ai_router.requests.get", lambda *a, **k: Response({"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3.1:latest"}, {"name": "nomic-embed-text:latest"}]}))
    def post(url, json, **kwargs):
        if url.endswith("/api/chat"):
            return Response({"message": {"content": '{"extracted_facts":[{"entity":"Mark","fact":"likes sushi","category":"preferences"}],"search_query":"Mark favorite dish"}'}})
        return Response({"embeddings": [[0.1, 0.2, 0.3]]})
    monkeypatch.setattr("core.local_ai_router.requests.post", post)
    router = LocalAIRouter(timeout=1)
    data = router.extract_facts("I am Mark and I like sushi. What is my favorite dish?")
    assert data["extracted_facts"][0]["entity"] == "Mark"
    assert data["search_query"] == "Mark favorite dish"


def test_router_embedding_and_tagging(monkeypatch):
    monkeypatch.setattr("core.local_ai_router.requests.get", lambda *a, **k: Response({"models": [{"name": "nomic-embed-text:latest"}, {"name": "llama3.1:latest"}]}))
    monkeypatch.setattr("core.local_ai_router.requests.post", lambda url, json, **k: Response({"embeddings": [[0.1, 0.2, 0.3]]}) if url.endswith("/api/embed") else Response({"message": {"content": "ok"}}))
    router = LocalAIRouter(timeout=1)
    assert router.embed("hello") == [[0.1, 0.2, 0.3]]
    assert router.tagged_fact("Mark", "favorite dish", "sushi").startswith("[Entity: Mark]")
