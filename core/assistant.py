from core.router import Router

from skills.conversation.conversation import (
    ConversationSkill,
)


class Assistant:

    def __init__(self):

        self.router = Router()

        self.router.register(
            ConversationSkill()
        )

    def handle(self, text):

        return self.router.route(text)