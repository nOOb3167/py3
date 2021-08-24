import asyncio
import logging
import pytest

ALOT = 99999

warn = logging.warning

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
async def test_a02() -> None:
    ran = False
    async def b() -> None:
        nonlocal ran
        ran = True
        try:
            await noopx()
        except BaseException as e:
            assert e.args[0] == 'xcanc'
            raise
    t = asyncio.get_running_loop().create_task(b())
    assert not t.done() and not ran
    await noop1()
    t.cancel('xcanc')
    assert not t.done() and ran
    try:
        await t
    except BaseException as e:
        pass
    with pytest.raises(asyncio.CancelledError) as ei:
        await t
    assert 'xcanc' in str(ei.value)


@pytest.mark.asyncio
async def test_a02a() -> None:
    async def c() -> None:
        with pytest.raises(asyncio.CancelledError) as ei:
            await noopx()
        assert 'xcanc' in str(ei.value)
        raise ei.value
    async def b() -> None:
        with pytest.raises(asyncio.CancelledError) as ei:
            await c()
        assert 'xcanc' in str(ei.value)
        raise ei.value
    t = asyncio.get_running_loop().create_task(b())
    assert not t.done()
    await noop1()
    t.cancel('xcanc')
    assert not t.done()
    with pytest.raises(asyncio.CancelledError) as ei:
        _, _ = await asyncio.wait([t])
        assert t.done() and t.cancelled()
        t.result()
    assert 'xcanc' in str(ei.value)


@pytest.mark.asyncio
async def test_a02b() -> None:
    async def b() -> None:
        with pytest.raises(asyncio.CancelledError) as ei:
            await noopx()
        raise RuntimeError('re') from ei.value
    t = asyncio.get_running_loop().create_task(b())
    await noop1()
    t.cancel('xcanc')
    with pytest.raises(RuntimeError) as ei:
        _, _ = await asyncio.wait([t])
        assert t.done() and not t.cancelled()
        t.result()
    assert 'xcanc' in str(ei.value.__cause__)


@pytest.mark.asyncio
async def test_a03a() -> None:
    async def b() -> None:
        await noopx()
    t = asyncio.get_running_loop().create_task(b())
    await noop1()
    t.cancel('xcanc')
    _, _ = await asyncio.wait([t])
    assert t.done() and not t.cancelled()


@pytest.mark.asyncio
async def test_a03b() -> None:
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
    #_, _ = await asyncio.wait([t])
    assert t.done() and t.cancelled()
    #ce = t._make_cancelled_error()
    warn(f'ce {ce}')

def test_zz() -> None:
    import importlib.resources
    import subprocess
    import sys
    with importlib.resources.path('pp', 'inout.py') as p:
        #subprocess.check_call([sys.executable, str(p)])
        with subprocess.Popen([sys.executable, '-u', str(p)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=False, encoding='UTF-8') as p:
            so, se = p.communicate('helloworld')
            warn(f'{so=} {se=}')
            assert p.returncode == 0

