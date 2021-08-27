def pytest_addoption(parser):
    group = parser.getgroup('pypath_src')
    group.addoption('--pypath_src', action='store_true')

def pytest_configure(config):
    if config.getoption('--pypath_src'):
        from pathlib import Path
        import sys
        if not (src := Path.cwd() / 'src').is_dir():
            raise RuntimeError(f'{src=} is not a directory')
        else:
            sys.path.insert(0, str(src))
