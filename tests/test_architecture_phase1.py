import inspect


def test_cognitive_loop_no_direct_gateway_execute():
    import brain.cognitive_loop as cl
    src = inspect.getsource(cl)
    assert "EXEC_GATEWAY.execute(" not in src, "cognitive_loop should not call EXEC_GATEWAY.execute directly"
