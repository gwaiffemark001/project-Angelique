import brain.cognitive_loop as cognitive


def test_explicit_commands_never_require_llm(monkeypatch):
    calls = []
    def fake_execute(name, args, **kwargs):
        calls.append((name, args))
        class Result:
            success = True
            output = f"executed:{name}"
            error = None
        return Result()
    monkeypatch.setattr(cognitive, "_call_through_execute_tool", fake_execute)
    monkeypatch.setattr(cognitive, "query_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))

    cognitive.resolve_user_query("what is the time and date", session_id="fast")
    cognitive.resolve_user_query("look for any file named project-Angelique on my laptop", session_id="fast")
    cognitive.resolve_user_query("open the browser and search flowers", session_id="fast")
    cognitive.resolve_user_query("send Mukundane Jerome Agaba a message on whatsapp saying hello", session_id="fast")

    assert [name for name, _ in calls] == ["search_files", "open_browser_and_search", "send_whatsapp"]

def test_user_log_variants_route_to_the_right_skill_without_llm(monkeypatch):
    calls=[]
    def fake_execute(name,args,**kwargs):
        calls.append((name,args))
        class Result:
            success=True; output='ok'; error=None
        return Result()
    monkeypatch.setattr(cognitive, '_call_through_execute_tool', fake_execute)
    monkeypatch.setattr(cognitive, 'query_llm', lambda *a, **k: (_ for _ in ()).throw(AssertionError('LLM called')))
    cognitive.resolve_user_query('look for project-Angelique on my pc', session_id='fast2')
    cognitive.resolve_user_query('look for any file named project-Angelique and tell me what is in it', session_id='fast2')
    cognitive.resolve_user_query('send Mukundane Jerome a message on whatsapp saying hello', session_id='fast2')
    cognitive.resolve_user_query('send Mukundane Jerome Agaba message on whatsapp saying hello', session_id='fast2')
    assert calls[0][0] == 'search_files'
    assert calls[1][0] == 'search_files'
    assert calls[2] == ('send_whatsapp', {'contact_name':'mukundane jerome','message':'hello'})
    assert calls[3] == ('send_whatsapp', {'contact_name':'mukundane jerome agaba','message':'hello'})
