import asyncio
import contextlib
import dataclasses
import dis
import logging
import pathlib
import sys
import traceback

import pp.taskgroup as tg
import pytest

ALOT = 99999

warn = logging.warning


def pexc(xei = None, *, z=sys.stderr):
    from _pytest._code.code import ExceptionInfo
    if xei:
        assert isinstance(xei, ExceptionInfo)
        ei = (type(xei.value), xei.value, xei.value.__traceback__)
    else:
        ei = sys.exc_info()
    assert ei[0] is not None and ei[1] is not None and ei[2] is not None
    te = traceback.TracebackException(ei[0], ei[1], ei[2])

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

    print(f"""== Exception {("|".join(list(te.format_exception_only())).strip())} ==""", file=z)

    for d in ds:
        print(f"""{d.name:<{mf1}}:{d.lineno:<{mf3}}::{d.fname:<{mf2}} = {d.line}""", file=z)

    print("== Exception END ==", file=z)


def ein(v):
    return type(v), v, v.__traceback__


def strexc(v: BaseException):
    return "".join(traceback.format_exception(type(v), v, v.__traceback__))


async def noop1() -> None:
    await asyncio.sleep(0)


async def noopx() -> None:
    while True:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_await_impl() -> None:
    fut = asyncio.get_running_loop().create_future()
    nit = 0

    async def b() -> None:
        await c()

    async def c() -> None:
        warn(f"prez")
        z = await XAwait()
        warn(f"posz {z=}")

    class XAwait:
        def __await__(self):
            if not fut.done():
                asyncio.get_running_loop().call_soon(cb)
                fut._asyncio_future_blocking = True # type: ignore
                yield fut
                assert fut.done()
            else:
                return fut.result()

    def cb():
        nonlocal nit
        if (nit := nit + 1) <= 3:
            warn("cb a")
            asyncio.get_running_loop().call_soon(cb)
        else:
            warn("cb b")
            fut.set_result("xdone")

    await b()


@pytest.mark.asyncio
async def test_zzz() -> None:
    async def b():
        try:
            await asyncio.sleep(ALOT)
        except asyncio.CancelledError as e:
            warn(f"1 {e=}")
            raise

    async def a():
        await b()

    async def a_():
        try:
            tt = asyncio.create_task(b())
            tt2 = asyncio.create_task(b())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            await tt
        except asyncio.CancelledError as e:
            warn(f"2 {e=}")
            raise

    t = [asyncio.create_task(a_()) for x in range(5)]
    await asyncio.sleep(0.1)
    t[0].cancel()
    done, pend = await asyncio.wait(t, timeout=1)
    s = await asyncio.gather(*done, return_exceptions=True)
    warn(f"{s=}")


@pytest.mark.asyncio
async def test_b() -> None:
    async def b() -> None:
        warn("presleep")
        await asyncio.sleep(ALOT)
        warn("postsleep")

    t = asyncio.get_running_loop().create_task(b())
    await asyncio.sleep(0)
    warn("fin")
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t


@pytest.mark.asyncio
async def test_a00() -> None:
    ran = False

    async def b() -> None:
        nonlocal ran
        ran = True

    t = asyncio.get_running_loop().create_task(b())
    await asyncio.sleep(0)
    assert ran and t.done()


@pytest.mark.asyncio
async def test_a01() -> None:
    ran = False

    async def b() -> None:
        nonlocal ran
        ran = True

    t = asyncio.get_running_loop().create_task(b())
    assert not ran and not t.done()


@pytest.mark.asyncio
async def test_a02a() -> None:
    async def b() -> None:
        with pytest.raises(asyncio.CancelledError) as ei:
            await noopx()
        raise RuntimeError() from ei.value

    t = asyncio.get_running_loop().create_task(b())
    await noop1()

    t.cancel("xcanc")
    _, _ = await asyncio.wait([t])
    assert t.done() and not t.cancelled()

    with pytest.raises(RuntimeError) as ei:
        t.result()
    assert "xcanc" in str(ei.value.__cause__)


@pytest.mark.asyncio
async def test_a02b() -> None:
    async def b() -> None:
        with pytest.raises(asyncio.CancelledError) as ei:
            await noopx()
        raise ei.value

    t = asyncio.get_running_loop().create_task(b())
    await noop1()

    t.cancel("xcanc")
    _, _ = await asyncio.wait([t])
    assert t.done() and t.cancelled()

    with pytest.raises(asyncio.CancelledError) as ei:
        t.result()
    assert "xcanc" in str(ei.value.__context__)

    warn(strexc(ei.value))


@pytest.mark.asyncio
async def test_a03() -> None:
    async def b() -> None:
        await noopx()

    t = asyncio.get_running_loop().create_task(b())

    t.cancel("xcanc")
    with pytest.raises(asyncio.CancelledError) as ei:
        await t
    ce = ei.value
    with pytest.raises(asyncio.CancelledError) as ei2:
        await t
    ce2 = ei2.value

    assert t.done() and t.cancelled()
    warn(f"ce {ce=} {ce2=}")


def test_zz() -> None:
    import importlib.resources
    import subprocess
    import sys

    with importlib.resources.path("pp", "inout.py") as pi:
        with subprocess.Popen(
            [sys.executable, "-u", str(pi)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            shell=False,
            encoding="UTF-8",
        ) as p:
            so, se = p.communicate("helloworld")
            warn(f"{so=} {se=}")
            assert p.returncode == 0


def test_dis() -> None:
    def a():
        with contextlib.nullcontext():
            pass

    dis.dis(a, file=sys.stderr)


def test_st0() -> None:
    def a():
        raise RuntimeError()

    def b():
        a()

    def c():
        try:
            b()
        except Exception as e:
            pexc()
            exc = e
        raise exc

    def d():
        c()

    try:
        d()
    except Exception as e:
        pexc()


def test_st1() -> None:
    def a():
        raise RuntimeError()

    def b():
        a()

    def c():
        try:
            b()
        except Exception as e:
            exc = e
        return exc

    def d():
        return c()

    def e():
        raise d()

    try:
        e()
    except Exception as _:
        pexc()


def test_dec_raise() -> None:
    @contextlib.contextmanager
    def m0():
        try:
            yield
        except Exception as e:
            pexc()
            exc = e
        raise exc  # type: ignore

    def c():
        with m0():
            raise RuntimeError()

    try:
        c()
    except Exception as e:
        pexc()


def test_dec_raise_from_exc() -> None:
    @contextlib.contextmanager
    def m0():
        try:
            yield
        except Exception as e:
            pexc()
            exc = e
        raise RuntimeError() from exc  # type: ignore

    def c():
        with m0():
            raise RuntimeError()

    try:
        c()
    except Exception as e:
        pexc()


def test_dec_throw_raise() -> None:
    @contextlib.contextmanager
    def m0():
        def q():
            yield

        z = q()
        next(z)
        try:
            yield
        except Exception as e:
            pexc()
            try:
                z.throw(e)
            except Exception as e2:
                assert e == e2
                exc = e
        raise exc  # type: ignore

    def c():
        with m0():
            raise RuntimeError()

    try:
        c()
    except Exception as e:
        pexc()


def test_gen_suppress() -> None:
    class m0:
        def __enter__(self):
            return self

        def __exit__(self, typ, val, tb):
            return False

    def c():
        with m0():
            raise RuntimeError()

    try:
        c()
    except Exception as e:
        pexc()


def test_gen_raise() -> None:
    class m0:
        def __enter__(self):
            return self

        def __exit__(self, typ, val, tb):
            raise val

    def c():
        with m0():
            raise RuntimeError()

    try:
        c()
    except Exception as e:
        pexc()


def test_gen_raise2() -> None:
    def gen():
        try:
            yield
        except Exception as e:
            r = RuntimeError("2")  # BaseException vs Exception
            r.__traceback__ = e.__traceback__
            raise r

    class m0:
        def __enter__(self):
            return self

        def __exit__(self, typ, val, tb):
            z = gen()
            next(z)
            assert val is not None
            z.throw(typ, val, tb)

    def e():
        raise RuntimeError("1")

    def d():
        e()

    def c():
        with m0():
            d()

    try:
        c()
    except Exception as _:
        pexc()


def test_gen_raise3() -> None:
    def gen():
        try:
            yield
        except Exception as e:
            raise

    class m0:
        def __enter__(self):
            return self

        def __exit__(self, typ, val, tb):
            z = gen()
            next(z)
            assert val is not None
            try:
                z.throw(typ, val, tb)
            except Exception as e:
                r = RuntimeError("2")  # BaseException vs Exception
                r.__traceback__ = e.__traceback__
                raise r from None

    def e():
        raise RuntimeError("1")

    def d():
        e()

    def c():
        with m0():
            d()

    try:
        c()
    except Exception as _:
        pexc()


@pytest.mark.asyncio
async def test_exc1() -> None:
    async def a():
        wa = tg.Waitee()
        await b(wa)

    async def b(wa: tg.Waitee):
        async with tg.Group() as w:
            await w.track_coro(c())
            await w.track_coro(c())
            await asyncio.sleep(0.1)

            try:
                await d()
            except:
                raise RuntimeError("b")

    async def c():
        try:
            await asyncio.sleep(1)
        except BaseException as e:
            pexc()
            raise

    async def d():
        raise RuntimeError("d")

    await a()

@pytest.mark.asyncio
async def test_exc2() -> None:
    async def a():
        async with tg.FallbaWait() as fw:
            await b()

    async def b():
        async with tg.Group() as gr:
            await gr.track_coro(c())
            await gr.track_coro(c())
            await asyncio.sleep(0.1)
            await d()

    async def c():
        try:
            await asyncio.sleep(1)
        except BaseException as e:
            pexc()
            raise

    async def d():
        raise RuntimeError("d")

    with pytest.raises(tg.GroupException) as ei:
        await a()
    pexc(ei)
