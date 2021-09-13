from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import enum
import itertools
import pathlib
import traceback
import typing

T = typing.TypeVar("T")

g_fallba: contextvars.ContextVar[Fallba] = contextvars.ContextVar("fallba")

class Restyp(enum.Enum):
    NA = 0
    VAL = 1
    EXC = 2


class WrapTask:

    task: asyncio.Task
    _restyp: Restyp
    _result: typing.Any

    def __init__(self, task: asyncio.Task) -> None:
        self.task = task
        self._restyp = Restyp.NA
        self._result = None

    @property
    def result(self) -> typing.Any:
        if self._restyp is Restyp.NA:
            self._result_set_try()
        if self._restyp is not Restyp.VAL:
            raise RuntimeError()
        return self._result

    @property
    def exception(self) -> BaseException:
        if self._restyp is Restyp.NA:
            self._result_set_try()
        if self._restyp is not Restyp.EXC:
            raise RuntimeError()
        return self._result

    def _result_set_try(self) -> None:
        if self.task.done():
            if self.task.cancelled():
                self._restyp = Restyp.EXC
                self._result = self.task._make_cancelled_error()  # type: ignore
            elif (exc := self.task.exception()) is not None:
                self._restyp = Restyp.EXC
                self._result = exc
            else:
                self._restyp = Restyp.VAL
                self._result = self.task.result()


class Waitee:
    tasks: set[WrapTask]

    def __init__(self):
        self.tasks = set[WrapTask]()

    def empty(self) -> bool:
        return not len(self.tasks)

    def cancel(self) -> None:
        for t in self.tasks:
            if not t.task.done():
                t.task.cancel()

    def _track_task(self, t: WrapTask) -> None:
        self.tasks.add(t)

    async def track_coro(self, coro: typing.Awaitable[T], name: str | None = None) -> None:
        self._track_task(WrapTask(asyncio.get_running_loop().create_task(coro, name=name)))

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
        ndone = len([t for t in self.tasks if t.task.done()])
        ncanc = len([t for t in self.tasks if t.task.cancelled()])
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
        # name = type(self).__name__
        # return f"""{name}({repr(self.src)}, {self.waitee})"""
        fmt = self._format()
        return "\n" + "\n".join(fmt)

    def _traceback_exc(self, val: BaseException):
        # assert val.__traceback__ is not None # TODO: apparently can be None
        return traceback.TracebackException.from_exception(val)

    def _format(self) -> list[str]:
        out = list[str]()

        te = self._traceback_exc(self.src)
        feo = self._format_exc_one(te, """== - """)
        out.extend(feo)

        for i, t in enumerate(self.waitee.tasks):
            te = self._traceback_exc(t.exception)
            feo = self._format_exc_one(te, f"""   {i} """)
            out.extend(feo)

        return out

    def _format_exc_one(self, te: traceback.TracebackException, hedr: str, _tbident: int = 4) -> list[str]:
        out = list[str]()

        fill = " " * len(hedr)
        tbident = " " * _tbident

        te = self._traceback_exc(self.src)
        feo = list(te.format_exception_only())
        out.extend([f"""{hedr if i == 0 else fill}{l}""".rstrip() for i, l in enumerate(feo)])
        out.extend([f"""{tbident}{l}""" for l in self._format_tb_one(te)])

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
            out.append(f"""{d.name:<{mf1}}:{d.lineno:<{mf3}}::{d.fname:<{mf2}} = {d.line}""".rstrip())

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
