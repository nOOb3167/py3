DOIT_CONFIG = {
    'default_tasks': ['t0']
}

def task_t0():
    return {
        'actions': ['py -m pip list'],
        'verbosity': 2,
    }
