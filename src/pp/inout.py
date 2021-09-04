import queue
import sys
import threading
import traceback

err: list[BaseException] = []
q = queue.Queue()

def ti() -> None:
    try:
        while True:
            d = sys.stdin.read(1)
            q.put(d)
            if not len(d):
                return
    except BaseException as e:
        err.append(e)
        traceback.print_exc(file=sys.stderr)

def to() -> None:
    try:
        while True:
            d = q.get()
            if not len(d):
                sys.stdout.close()
                return
            z = sys.stdout.write(d)
            assert z == len(d)
            sys.stdout.flush()
    except BaseException as e:
        err.append(e)
        traceback.print_exc(file=sys.stderr)

def run() -> None:
    t1 = threading.Thread(target=ti)
    t2 = threading.Thread(target=to)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    if len(err):
        sys.exit(1)

if __name__ == '__main__':
    run()
