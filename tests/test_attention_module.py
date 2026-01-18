from houndmind_ai.behavior.attention import AttentionModule


class DummyDog:
    def __init__(self):
        self.calls = []

    def head_move(self, coords, speed=70):
        self.calls.append((coords, speed))

    def wait_head_done(self):
        return None


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_attention_turns_head_on_sound():
    ctx = DummyContext()
    ctx.set("pidog", DummyDog())
    ctx.set("settings", {"attention": {"enabled": True, "respect_scanning": False}})
    ctx.set("perception", {"sound": True, "sound_direction": 90})

    module = AttentionModule("attention")
    module.tick(ctx)

    dog = ctx.get("pidog")
    assert dog.calls, "head_move should be called when sound is detected"
