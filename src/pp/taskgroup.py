from __future__ import annotations

import asyncio
import collections.abc
import contextlib
import dataclasses
import typing

T: typing.TypeAlias = typing.TypeVar("T")


class Waitee:
    @dataclasses.dataclass
    class D:
        result: list[typing.Any]

    tasks: dict[asyncio.Task, D] = {}

    def __init__(self, tasks: typing.Iterable[asyncio.Task[T]]):
        for t in tasks:
            self.tasks[t] = self.D([t.result()] if t.done() else [])

    def empty(self) -> bool:
        return not len(self.tasks)

    def cancel(self) -> None:
        for t in self.tasks.keys():
            if not t.done():
                t.cancel()

    def steal_from(self, waitee: Waitee, fn=lambda t: True) -> None:
        xfer = [t for t in waitee.tasks if fn(t)]
        for t in xfer:
            self.tasks[t] = self.D([t.result()] if t.done() else [])
        waitee.tasks = []


class Waiter:
    waitee: Waitee = Waitee([])

    def track(self, waitee: Waitee) -> None:
        self.waitee.steal_from(waitee)

    async def wait(self) -> None:
        done, pending = asyncio.wait(self.waitee.tasks)


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


@typing.overload
def make_group_exception(src: Exception) -> GroupException:
    ...


@typing.overload
def make_group_exception(src: BaseException) -> GroupBaseException:
    ...


def make_group_exception(src: BaseException, waitee: Waitee):
    # match src:
    #     case _ if isinstance(src, Exception):
    #         return GroupException(src, waitee)
    #     case _ if isinstance(src, BaseException):
    #         return GroupBaseException(src, waitee)
    #     case _:
    #         raise RuntimeError()
    if isinstance(src, Exception):
        return GroupException(src, waitee)
    if isinstance(src, BaseException):
        return GroupBaseException(src, waitee)
    raise NotImplemented()


class Group(contextlib.AbstractAsyncContextManager[T]):
    waiter: Waiter
    waitee: Waitee = Waitee([])

    def __init__(self, *, waiter: Waiter):
        self.waiter = waiter

    async def __aenter__(self):
        return self

    async def __aexit__(self, typ, val, tb):
        waitee = Waitee([])
        waitee.steal_from(self.waitee, fn=lambda t: not t.done())  # FIXME: maybe steal all
        waitee.cancel()

        self.waiter.track(waitee)

        # FIXME: from none? (we have val stored)
        if val is not None:
            raise make_group_exception(val, waitee) from None

    def track(self, coro: collections.abc.Awaitable[T]):
        self.waitee.steal_from(Waitee([asyncio.get_running_loop().create_task(coro)]))
