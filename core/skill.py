from abc import ABC, abstractmethod


class Skill(ABC):
    """
    Every Angelique skill inherits from this class.
    """

    @abstractmethod
    def can_handle(self, text: str) -> bool:
        pass

    @abstractmethod
    def execute(self, text: str) -> str:
        pass