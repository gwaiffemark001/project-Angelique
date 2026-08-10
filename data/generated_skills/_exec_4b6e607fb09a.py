def main(**kwargs):
    if 'provide' in kwargs:
        if kwargs['provide'] == 'help':
            print("Available options: help, exit, example")
        elif kwargs['provide'] == 'exit':
            print("Exiting program.")
            exit()
        elif kwargs['provide'] == 'example':
            print("This is an example.")
        else:
            print("Invalid option. Please use 'help' for available options.")
    else:
        print("Invalid instruction. Please use 'provide' to specify an action.")

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
