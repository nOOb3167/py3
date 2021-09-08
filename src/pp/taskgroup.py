from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import pathlib
import traceback
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
        return f"""{name}(tasks={tasks}, ndone={ndone})"""


class Fallba:
    que_cond: asyncio.Condition
    que: asyncio.Queue[asyncio.Task]
    waitee: Waitee
    waiter: asyncio.Task
    waiter_err: list[BaseException]
    exiting: bool

    def __init__(self):
        self.que_cond = asyncio.Condition()
        self.que = asyncio.Queue[asyncio.Task]()
        self.waitee = Waitee()
        self.waiter = asyncio.get_running_loop().create_task(
            self._waiter(), name=f"{type(self).__name__}::{self._waiter.__name__}"
        )
        self.waiter_err = []
        self.exiting = False

    async def _waiter(self) -> None:
        await self._waiter_loop()
        if len(self.waiter_err):
            raise RuntimeError(self.waiter_err)  # FIXME: raise BaseException should any be in waiter_err

    async def _waiter_loop(self) -> None:
        while True:
            try:
                async with self.que_cond:
                    await self.que_cond.wait_for(self._waiter_cond)
                    ts = [self.que.get_nowait() for x in range(self.que.qsize())]
                await self._waiter_wait_all(ts)
                if self.exiting and not self.que.qsize():
                    return
            except asyncio.CancelledError as e:
                raise asyncio.CancelledError(self.waiter_err) from e
            except BaseException as e:
                self.waiter_err.append(e)

    def _waiter_cond(self) -> bool:
        return self.que.qsize() > 0 or self.exiting

    async def _waiter_wait_all(self, tasks: typing.Iterable[asyncio.Task]) -> None:
        # resist cancellation - propagate only when finished waiting
        errs = list[BaseException]()
        try:
            pending = set(tasks)
            while len(pending):
                try:
                    done, pending = await asyncio.wait(pending)
                except BaseException as e:
                    self.waiter_err.append(e)
        finally:
            if len(errs):
                isc = any(x for x in errs if isinstance(x, asyncio.CancelledError))
                if isc:
                    carrier = asyncio.CancelledError(errs)
                else:
                    carrier = RuntimeError(errs)
                raise carrier

    async def _wait_exited(self) -> None:
        done, pending = await asyncio.wait(self.waiter)
        assert self.waiter.done()

    async def exit(self) -> None:
        async with self.que_cond:
            self.exiting = True
        await self._wait_exited()


class FallbaWait:
    fallba: Fallba

    def __init__(self):
        self.fallba = g_fallba.get()

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, typ, val, tb) -> typing.Any:
        await self.fallba.exit()


g_fallba = contextvars.ContextVar("fallba", default=Fallba())


class _GroupExceptionMixin:
    src: BaseException
    waitee: Waitee

    def __init__(self, src: BaseException, waitee: Waitee):
        self.src = src
        self.waitee = waitee

    def __str__(self):
        name = type(self).__name__
        return f"""{name}({repr(self.src)}, {self.waitee})"""


class GroupBaseException(_GroupExceptionMixin, BaseException):
    def __init__(self, src: BaseException, waitee: Waitee):
        super().__init__(src, waitee)

    def __str__(self):
        return super().__str__()

    def _format(self) -> list[str]:
        return self._format_one(self.src)

    def _format_one(self, val: BaseException) -> list[str]:
        assert val.__traceback__ is not None

        out = list[str]()

        te = traceback.TracebackException(type(val), val, val.__traceback__)

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

        out.append(f"""== Exception {("|".join(list(te.format_exception_only())).strip())} ==""")

        for d in ds:
            out.append(f"""{d.name:<{mf1}}:{d.lineno:<{mf3}}::{d.fname:<{mf2}} = {d.line}""")

        out.append("== Exception END ==")

        return out


class GroupException(_GroupExceptionMixin, Exception):
    def __init__(self, src: BaseException, waitee: Waitee):
        super().__init__(src, waitee)

    def __str__(self):
        return super().__str__()


class GroupExceptionWait:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, typ, val, tb) -> typing.Any:
        if isinstance(val, GroupException) or isinstance(val, GroupBaseException):
            await val.waitee.wait()


class Group:
    waitee: Waitee = Waitee()
    fallba: Fallba

    def __init__(self):
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
