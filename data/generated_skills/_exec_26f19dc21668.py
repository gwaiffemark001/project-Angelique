def main(**kwargs):
    return 7 ** 2


if __name__ == '__main__':
    import json, sys, traceback
    try:
        res = main(**{})
        print('<<RESULT_START>>')
        import json as _json
        print(_json.dumps({'result': res}))
        print('<<RESULT_END>>')
    except Exception:
        print('<<ERROR_START>>')
        traceback.print_exc()
        print('<<ERROR_END>>')
        sys.exit(1)
