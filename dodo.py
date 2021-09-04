import pathlib

DOIT_CONFIG = {"default_tasks": ["default"]}


def task_default() -> dict:
    return {"actions": [lambda: None]}


def task_clean_dist() -> dict:
    def clean_dist() -> None:
        tgz = pathlib.Path(".").glob("dist/*.tar.gz")
        whl = pathlib.Path(".").glob("dist/*.whl")
        for f in list(tgz) + list(whl):
            f.unlink()

    return {"actions": [clean_dist]}


def task_build_dist() -> dict:
    return {"actions": ["py -m build --sdist --wheel ."], "task_dep": ["clean_dist"]}


def task_build_deps() -> dict:
    return {
        "actions": ["pip-compile --upgrade pyproject.toml requirements-dev.in"],
        "file_dep": ["pyproject.toml", "requirements-dev.in"],
        "targets": ["requirements.txt"],
    }


def task_upload_test() -> dict:
    return {
        "actions": ["py -m twine upload -r testpypi dist/*"],
        "task_dep": ["build_dist"],
    }


def task_test_tox() -> dict:
    return {"actions": ["py -m tox"], "verbosity": 2}
