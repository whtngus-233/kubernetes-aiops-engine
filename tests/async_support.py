"""Native ASGI tests; retain real FastAPI validation and worker execution.

Some managed sandboxes deny socketpair writes (EPERM), including asyncio's
cross-thread wakeup socket. Only in that environment use a bounded selector
wait so queued callbacks can run. This does not mock endpoints or workers.
"""
import asyncio
import selectors
import socket
import httpx
import unittest


def loop_factory():
    restricted = False
    with _socket_pair() as pair:
        try:
            pair[0].send(b'x')
        except PermissionError:
            restricted = True
    if not restricted:
        return asyncio.new_event_loop()

    class BoundedSelector(selectors.DefaultSelector):
        def select(self, timeout=None):
            return super().select(.01 if timeout is None else min(timeout, .01))

    return asyncio.SelectorEventLoop(BoundedSelector())


from contextlib import contextmanager

@contextmanager
def _socket_pair():
    left, right = socket.socketpair()
    try:
        yield left, right
    finally:
        left.close()
        right.close()


def async_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')


class AsyncAPITestCase(unittest.IsolatedAsyncioTestCase):
    """Python 3.12 equivalent of 3.13's IsolatedAsyncioTestCase.loop_factory."""
    def _setupAsyncioRunner(self):
        assert self._asyncioRunner is None
        self._asyncioRunner = asyncio.Runner(debug=False, loop_factory=loop_factory)
