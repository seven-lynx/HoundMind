import sys
import pathlib
import importlib.util

print('sys.path sample:', sys.path[:5])
print('cwd:', pathlib.Path.cwd())
spec = importlib.util.find_spec('tools')
print('tools spec:', spec)
try:
    import tools
    print('tools package file:', getattr(tools, '__file__', None))
except Exception as e:
    print('import tools failed:', e)
