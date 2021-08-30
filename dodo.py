import pathlib

DOIT_CONFIG = {"default_tasks": ["t0"]}


def task_t0():
    return {
        "actions": ["py -m pip list"],
        "verbosity": 2,
    }


def task_clean_dist():
    def clean_dist():
        tgz = pathlib.Path(".").glob("dist/*.tar.gz")
        whl = pathlib.Path(".").glob("dist/*.whl")
        for f in list(tgz) + list(whl):
            f.unlink()

    return {
        "actions": [clean_dist],
    }


def task_build():
    return {
        "actions": ["py -m build --sdist --wheel ."],
        "task_dep": ["clean_dist"],
    }


def task_upload_test():
    return {
        "actions": ["py -m twine upload -r testpypi dist/*"],
        "task_dep": ["build"],
        "verbosity": 2,
    }
