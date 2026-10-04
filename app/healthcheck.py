"""Standalone Docker probe: stdlib only, no app import, shell or worker pool."""
import http.client
import json
import sys
import time


def check_health(connection_factory=http.client.HTTPConnection, clock=time.monotonic):
    deadline = clock() + 2
    connection = connection_factory('127.0.0.1', 8000, timeout=2)
    try:
        connection.request('GET', '/health')
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        if connection.sock is not None:
            connection.sock.settimeout(remaining)
        response = connection.getresponse()
        # Bound both bytes and elapsed time; the Docker outer limit stays 3s.
        if response.status != 200:
            return False
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        if connection.sock is not None:
            connection.sock.settimeout(remaining)
        body = response.read(1025)
        return (len(body) <= 1024 and clock() < deadline
                and json.loads(body) == {'status': 'ok', 'mode': 'read-only', 'store': 'memory'})
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


if __name__ == '__main__':
    sys.exit(0 if check_health() else 1)
