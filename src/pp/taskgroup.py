from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import itertools
import pathlib
import traceback
import typing

T = typing.TypeVar("T")

g_fallba: contextvars.ContextVar[Fallba] = contextvars.ContextVar("fallba")


class WrapTask:
    task: asyncio.Task
    result: typing.Any
    exception: typing.Any

    def __init__(self, task: asyncio.Task) -> None:
        self.task = task


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
        self.tasks[t] = self.D(result=[t.result()] if t.done() and not t.cancelled() else [])

    async def track_coro(self, coro: typing.Awaitable[T], name: str | None = None) -> None:
        self._track_task(asyncio.get_running_loop().create_task(coro, name=name))

    def track_from(self, waitee: Waitee) -> None:
        for t in waitee.tasks:
            self._track_task(t)

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
        ncanc = len([t for t in self.tasks if t.cancelled()])
        return f"""{name}(tasks={tasks}, ndone={ndone}, ncanc={ncanc})"""


class _Exiting:
    pass


class Fallba:
    que_cond: asyncio.Condition
    que: asyncio.Queue[asyncio.Task | _Exiting]
    waitee: Waitee
    waiter: asyncio.Task
    waiter_err: list[BaseException]
    exiting: bool

    def __init__(self):
        self.que_cond = asyncio.Condition()
        self.que = asyncio.Queue[asyncio.Task | _Exiting]()
        self.waitee = Waitee()
        self.waiter = asyncio.get_running_loop().create_task(
            self._waiter(), name=f"{type(self).__name__}::{self._waiter.__name__}"
        )
        self.waiter_err = []

    async def _waiter(self) -> None:
        await self._waiter_loop()
        if len(self.waiter_err):
            raise RuntimeError(self.waiter_err)  # TODO: raise BaseException should any be in waiter_err

    async def _waiter_loop(self) -> None:
        while True:
            async with self.que_cond:
                await self.que_cond.wait_for(self._waiter_cond)
                ds = [self.que.get_nowait() for x in range(self.que.qsize())]
            ts = typing.cast(
                typing.Iterable[asyncio.Task], itertools.takewhile(lambda x: isinstance(x, asyncio.Task), ds)
            )
            exiting = any(isinstance(x, _Exiting) for x in ds)  # TODO: O(N)
            await self._waiter_wait_all(ts)
            if exiting:
                return

    def _waiter_cond(self) -> bool:
        return self.que.qsize() > 0

    async def _waiter_wait_all(self, tasks: typing.Iterable[asyncio.Task]) -> None:
        pending = set(tasks)
        while len(pending):
            done, pending = await asyncio.wait(pending)

    async def _wait_exited(self) -> None:
        done, pending = await asyncio.wait([self.waiter])
        assert self.waiter.done()

    async def exit(self) -> None:
        async with self.que_cond:
            self.que.put_nowait(_Exiting())
            self.que_cond.notify()
        await self._wait_exited()


class FallbaWait:
    _fallba: Fallba
    _token: contextvars.Token[Fallba]

    async def __aenter__(self) -> None:
        self._fallba = Fallba()
        self._token = g_fallba.set(self._fallba)
        return None

    async def __aexit__(self, typ, val, tb) -> typing.Any:
        try:
            await self._fallba.exit()
        finally:
            g_fallba.reset(self._token)


class _GroupExceptionMixin:
    src: BaseException
    waitee: Waitee

    def __init__(self, src: BaseException, waitee: Waitee):
        self.src = src
        self.waitee = waitee

    def __str__(self):
        name = type(self).__name__
        return f"""{name}({repr(self.src)}, {self.waitee})"""

    def _waitee_results_available(self):
        ts = self.waitee.tasks
        for t in ts:
            if t.cancelled():
                e = t._make_cancelled_error()  # type: ignore
            elif t.done():
                pass

    def _traceback_exc(self, val: BaseException):
        assert val.__traceback__ is not None
        return traceback.TracebackException(type(val), val, val.__traceback__)

    def _format(self) -> list[str]:
        out = list[str]()
        te = self._traceback_exc(self.src)
        out.extend(self._format_exc_one(te))
        out.extend(self._format_tb_one(te))
        return out

    def _format_exc_one(self, te: traceback.TracebackException) -> list[str]:
        out = list[str]()
        hedr = """== Exception """
        fill = " " * len(hedr)
        exco = list(te.format_exception_only())
        for i, l in enumerate(exco):
            out.append(f"""{hedr if i == 0 else fill}{l}""")
        return out

    def _format_tb_one(self, te: traceback.TracebackException) -> list[str]:
        out = list[str]()

        @dataclasses.dataclass
        class D:
            name: str
            fname: str
            lineno: int
            line: str

        ds = list(reversed([D(pathlib.Path(f.filename).name, f.name, f.lineno, f.line) for f in te.stack]))
        mf1 = len(max(ds, key=lambda x: len(x.name)).name)
        mf2 = len(max(ds, key=lambda x: len(x.fname)).fname)
        mf3 = len(str(max(ds, key=lambda x: len(str(x.lineno))).lineno))

        for d in ds:
            out.append(f"""{d.name:<{mf1}}:{d.lineno:<{mf3}}::{d.fname:<{mf2}} = {d.line}""")

        return out


class GroupBaseException(_GroupExceptionMixin, BaseException):
    def __init__(self, src: BaseException, waitee: Waitee):
        super().__init__(src, waitee)

    def __str__(self):
        return super().__str__()


class GroupException(_GroupExceptionMixin, Exception):
    def __init__(self, src: BaseException, waitee: Waitee):
        super().__init__(src, waitee)

    def __str__(self):
        return super().__str__()


class GroupExceptionWait:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, typ, val, tb) -> typing.Any:
        raise NotImplementedError()


class Group:
    waitee: Waitee
    fallba: Fallba

    def __init__(self):
        self.waitee = Waitee()
        self.fallba = g_fallba.get()

    async def __aenter__(self) -> Waitee:
        return self.waitee

    async def __aexit__(self, typ, val, tb) -> bool | None:
        self.waitee.cancel()
        self.fallba.waitee.track_from(self.waitee)

        if val is not None:
            if isinstance(val, asyncio.CancelledError):
                return False
            elif isinstance(val, Exception):
                raise GroupException(val, self.waitee)
            elif isinstance(val, BaseException):
                raise GroupBaseException(val, self.waitee)
            else:
                raise NotImplementedError()
