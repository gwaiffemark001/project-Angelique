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