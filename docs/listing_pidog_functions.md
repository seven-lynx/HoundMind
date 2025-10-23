# Listing PiDog Functions Safely

This short guide shows how to list available methods on a PiDog instance without baking hardware-dependent code into the core library.

## Why this is here

- Keeps hardware probing out of `canine_core` to avoid side-effects during imports.
- Provides a copy-paste snippet for developers who want to introspect the PiDog API on-device.

## Usage

Run this script directly on your PiDog-enabled environment (where the `pidog` package and hardware are available).

```python
#!/usr/bin/env python3
import time

try:
    from pidog import Pidog
except Exception as e:
    print("pidog package not available:", e)
    raise SystemExit(1)


def list_pidog_functions():
    """List user-facing methods/attributes on Pidog instance."""
    dog = Pidog()
    try:
        # Ensure robot is up and responsive before introspection
        try:
            dog.do_action("stand", speed=120)
            dog.wait_all_done()
        except Exception:
            pass

        methods = [m for m in dir(dog) if not m.startswith("__")]
        print("\nAvailable PiDog methods/attributes:\n")
        for m in methods:
            print("-", m)
    finally:
        try:
            dog.close()
        except Exception:
            pass


if __name__ == "__main__":
    list_pidog_functions()
```

## Notes

- This script intentionally avoids importing from `canine_core`.
- It’s safe to modify for your needs (e.g., filter methods by prefix or print docstrings).
- If you’re running on a development host without PiDog hardware, the import will fail by design.
