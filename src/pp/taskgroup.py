from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import typing

T = typing.TypeVar("T")


class Waitee:
    @dataclasses.dataclass
    class D:
        result: list[typing.Any]

    tasks: dict[asyncio.Task, D] = {}

    def __init__(self, tasks: typing.Iterable[asyncio.Task[T]] = []):
        for t in tasks:
            self._track_task(t)

    def empty(self) -> bool:
        return not len(self.tasks)

    def cancel(self) -> None:
        for t in self.tasks.keys():
            if not t.done():
                t.cancel()

    def _track_task(self, t: asyncio.Task[T]) -> None:
        self.tasks[t] = self.D(result=[t.result()] if t.done() else [])

    async def track_coro(self, coro: typing.Awaitable[T], name: str | None = None) -> None:
        self._track_task(asyncio.get_running_loop().create_task(coro, name=name))

    def steal_from(self, waitee: Waitee) -> None:
        try:
            for t in waitee.tasks:
                self._track_task(t)
        finally:
            waitee.tasks.clear()

    def __str__(self) -> str:
        name = type(self).__name__
        tasks = len(self.tasks)
        ndone = len([t for t in self.tasks if not t.done])
        return f"""{name}(tasks={tasks}, ndone={ndone})"""


class GroupBaseException(BaseException):
    src: BaseException
    waitee: Waitee

    def __init__(self, src: BaseException, waitee: Waitee):
        self.src = src
        self.waitee = waitee


class GroupException(Exception):
    src: BaseException
    waitee: Waitee

    def __init__(self, src: Exception, waitee: Waitee):
        self.src = src
        self.waitee = waitee

    def __str__(self):
        return f"""GroupException({repr(self.src)}, {self.waitee})"""


class Group(contextlib.AbstractAsyncContextManager[T]):
    waitee: Waitee

    def __init__(self, *, waitee: Waitee):
        self.waitee = waitee

    async def __aenter__(self) -> Waitee:
        return self.waitee

    async def __aexit__(self, typ, val, tb) -> typing.Any:
        self.waitee.cancel()

        if val is not None:
            if isinstance(val, Exception):
                raise GroupException(val, self.waitee)
            if isinstance(val, BaseException):
                raise GroupBaseException(val, self.waitee)
            raise NotImplementedError()
