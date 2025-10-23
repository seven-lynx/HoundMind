from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packmind.core.context import AIContext

class BaseBehavior(ABC):
    """
    Abstract base class for all AI behaviors.
    """

    @abstractmethod
    def execute(self, context: 'AIContext') -> None:
        """
        Execute the behavior's logic.

        This method is called on every tick of the orchestrator's main loop
        when this behavior is active.

        Args:
            context: The shared AI context object.
        """
        pass

    def on_enter(self, context: 'AIContext') -> None:
        """
        Called when the state machine enters this behavior.
        Optional for setup logic.
        """
        pass

    def on_exit(self, context: 'AIContext') -> None:
        """
        Called when the state machine exits this behavior.
        Optional for cleanup logic.
        """
        pass
