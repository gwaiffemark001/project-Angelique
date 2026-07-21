from typing import List
from core.skill import Skill


class Router:

    def __init__(self):

        self.skills: List[Skill] = []

    def register(self, skill: Skill):

        self.skills.append(skill)

    def route(self, text: str):

        for skill in self.skills:

            if skill.can_handle(text):

                return skill.execute(text)

        return None