import pathlib

DOIT_CONFIG = {"default_tasks": ["default"]}


def task_default():
    return {"actions": [lambda: None]}


def task_clean_dist():
    def clean_dist():
        tgz = pathlib.Path(".").glob("dist/*.tar.gz")
        whl = pathlib.Path(".").glob("dist/*.whl")
        for f in list(tgz) + list(whl):
            f.unlink()

    return {"actions": [clean_dist]}


def task_build_dist():
    return {"actions": ["py -m build --sdist --wheel ."], "task_dep": ["clean_dist"]}


def task_build_deps():
    return {
        "actions": ["pip-compile pyproject.toml requirements-dev.in"],
        "file_dep": ["pyproject.toml", "requirements-dev.in"],
        "targets": ["requirements.txt"],
    }


def task_upload_test():
    return {
        "actions": ["py -m twine upload -r testpypi dist/*"],
        "task_dep": ["build_dist"],
    }


def task_test_tox():
    return {"actions": ["py -m tox"], "verbosity": 2}
