"""A wrong public exception fails on the contract assertion, not test preparation."""
from contextlib import contextmanager
from types import SimpleNamespace

@contextmanager
def public_error(expected):
    caught=SimpleNamespace(value=None)
    try:
        yield caught
    except Exception as error:
        caught.value=error
    assert isinstance(caught.value,expected), f'Expected {expected.__name__}; received {type(caught.value).__name__}: {caught.value}'
