from houndmind_ai.behavior.attention import AttentionModule
from houndmind_ai.hal.fake import FakeDogHAL


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_attention_turns_head_on_sound():
    ctx = DummyContext()
    hal = FakeDogHAL()
    ctx.set("hal", hal)
    ctx.set("settings", {"attention": {"enabled": True, "respect_scanning": False}})
    ctx.set("perception", {"sound": True, "sound_direction": 90})

    module = AttentionModule("attention")
    module.tick(ctx)

    head_moves = [params for name, params in hal.calls if name == "head"]
    assert head_moves, "the head should be asked to turn when sound is detected"
    # `wait=False`: a behaviour module must never block the decision loop on a servo move.
    assert head_moves[0]["wait"] is False
