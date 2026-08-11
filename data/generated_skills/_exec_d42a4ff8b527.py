def main(**kwargs):
    if 'provide' in kwargs:
        if kwargs['provide'] == 'help':
            print("This script provides help on how to use it.")
        elif kwargs['provide'] == 'information':
            print("This script provides information on a given topic.")
        else:
            print("Invalid option. Please use 'help' or 'information'.")
    else:
        print("Please provide an option to use this script.")

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
