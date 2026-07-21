from core.skill import Skill


class ConversationSkill(Skill):

    def can_handle(self, text: str):

        return True

    def execute(self, text: str):

        return (
            "Conversation skill received: "
            + text
        )