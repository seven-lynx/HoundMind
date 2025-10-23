from __future__ import annotations
from typing import Dict

from packmind.core.types import BehaviorState
from packmind.behaviors.base_behavior import BaseBehavior


class BehaviorRegistry:
    """
    Simple registry mapping BehaviorState -> Behavior instance.
    Orchestrator can source its behavior table from here.
    """

    def __init__(self) -> None:
        self._behaviors: Dict[BehaviorState, BaseBehavior] = {}

    def register(self, state: BehaviorState, behavior: BaseBehavior) -> None:
        self._behaviors[state] = behavior

    def get(self, state: BehaviorState) -> BaseBehavior | None:
        return self._behaviors.get(state)

    def all(self) -> Dict[BehaviorState, BaseBehavior]:
        return dict(self._behaviors)
