def main(**kwargs):
    if 'provide' in kwargs:
        if kwargs['provide'] == 'help':
            print("Available options: help, exit")
        elif kwargs['provide'] == 'exit':
            print("Exiting program.")
            exit()
        else:
            print("Unknown option. Please use 'help' for available options.")
    else:
        print("Unknown instruction. Please use 'help' for available options.")

if __name__ == "__main__":
    main()

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
