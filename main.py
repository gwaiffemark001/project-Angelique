from core.assistant import Assistant


assistant = Assistant()

while True:

    user = input("You: ")

    if user.lower() == "exit":

        break

    response = assistant.handle(user)

    print()

    print("Angelique:", response)

    print()