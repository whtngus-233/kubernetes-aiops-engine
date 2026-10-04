"""Probe failures and health independence from AnyIO thread capacity."""
import asyncio
import inspect
from unittest.mock import Mock
import unittest
import anyio
from app.api import create_app
from app.config import Settings
from app.healthcheck import check_health
from tests.async_support import AsyncAPITestCase, async_client


class HealthEndpointTests(AsyncAPITestCase):
    async def test_health_without_threadpool_capacity(self):
        engine = Mock()
        app = create_app(Settings(), engine=engine)
        endpoint = next(r.endpoint for r in app.routes if getattr(r, 'path', None) == '/health')
        self.assertTrue(inspect.iscoroutinefunction(endpoint))
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 1
        await limiter.acquire()
        try:
            async with async_client(app) as client:
                response = await asyncio.wait_for(client.get('/health'), 1)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'status': 'ok', 'mode': 'read-only', 'store': 'memory'})
            engine.analyze.assert_not_called()
        finally:
            limiter.release()
            limiter.total_tokens = previous


class ProbeTests(unittest.TestCase):
    def connection(self, status=200, body=b'{"status":"ok","mode":"read-only","store":"memory"}'):
        connection = Mock()
        connection.getresponse.return_value.status = status
        connection.getresponse.return_value.read.return_value = body
        return connection

    def test_success_and_close(self):
        connection = self.connection()
        factory = Mock(return_value=connection)
        self.assertTrue(check_health(factory))
        factory.assert_called_once_with('127.0.0.1', 8000, timeout=2)
        connection.close.assert_called_once()
        connection.getresponse.return_value.read.assert_called_once_with(1025)

    def test_failure_status_body_timeout_and_disconnect(self):
        for connection in (self.connection(503), self.connection(body=b'invalid'),
                           self.connection(body=b'{}'), self.connection(body=b'x'*1025)):
            with self.subTest(connection=connection):
                self.assertFalse(check_health(lambda *a, **kw: connection))
                connection.close.assert_called_once()
        for error in (TimeoutError(), ConnectionRefusedError()):
            connection = self.connection()
            connection.request.side_effect = error
            self.assertFalse(check_health(lambda *a, **kw: connection))
            connection.close.assert_called_once()

    def test_deadline_failure(self):
        connection = self.connection()
        self.assertFalse(check_health(lambda *a, **kw: connection, Mock(side_effect=[0, 3])))
        connection.close.assert_called_once()

    def test_response_consuming_budget_fails(self):
        connection = self.connection()
        clock = Mock(side_effect=[0, .2, .5, 2.1])
        self.assertFalse(check_health(lambda *a, **kw: connection, clock))
        self.assertEqual(connection.sock.settimeout.call_args_list[0].args, (1.8,))
        self.assertEqual(connection.sock.settimeout.call_args_list[1].args, (1.5,))
        connection.close.assert_called_once()
