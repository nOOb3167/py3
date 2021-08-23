import py2.a

def qq() -> int:
    return 3

def test_a():
    py2.a.z(3)
    #py2.a.q()
    z: str = qq()
    print('z')
    #assert 0