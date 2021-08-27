import contextlib
import importlib.metadata

with contextlib.suppress(Exception):
    __version__ = '0.0'
    __version__ = importlib.metadata.version('perder_si_py3')
