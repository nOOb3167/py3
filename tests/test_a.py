import asyncio
import logging
import pytest
import re
import traceback

ALOT = 99999

warn = logging.warning

def strexc(v: BaseException):
    return ''.join(traceback.format_exception(type(v), v, v.__traceback__))

async def noop1() -> None:
    await asyncio.sleep(0)

async def noopx() -> None:
    while True:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_b() -> None:
    async def b() -> None:
        warn('presleep')
        await asyncio.sleep(ALOT)
        warn('postsleep')
    t = asyncio.get_running_loop().create_task(b())
    await asyncio.sleep(0)
    warn('fin')


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

    t.cancel('xcanc')
    _, _ = await asyncio.wait([t])
    assert t.done() and not t.cancelled()
    
    with pytest.raises(RuntimeError) as ei:
        t.result()
    assert 'xcanc' in str(ei.value.__cause__)


@pytest.mark.asyncio
async def test_a02b() -> None:
    async def b() -> None:
        with pytest.raises(asyncio.CancelledError) as ei:
            await noopx()
        raise ei.value
    
    t = asyncio.get_running_loop().create_task(b())
    await noop1()

    t.cancel('xcanc')
    _, _ = await asyncio.wait([t])
    assert t.done() and t.cancelled()

    with pytest.raises(asyncio.CancelledError) as ei:
        t.result()
    assert 'xcanc' in str(ei.value.__context__)

    warn(strexc(ei.value))


@pytest.mark.asyncio
async def test_a03() -> None:
    async def b() -> None:
        await noopx()

    t = asyncio.get_running_loop().create_task(b())

    t.cancel('xcanc')
    with pytest.raises(asyncio.CancelledError) as ei:
        await t
    ce = ei.value
    with pytest.raises(asyncio.CancelledError) as ei2:
        await t
    ce2 = ei2.value

    assert t.done() and t.cancelled()
    warn(f'ce {ce=} {ce2=}')


def test_zz() -> None:
    import importlib.resources
    import subprocess
    import sys
    with importlib.resources.path('pp', 'inout.py') as pi:
        with subprocess.Popen([sys.executable, '-u', str(pi)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=False, encoding='UTF-8') as p:
            so, se = p.communicate('helloworld')
            warn(f'{so=} {se=}')
            assert p.returncode == 0

