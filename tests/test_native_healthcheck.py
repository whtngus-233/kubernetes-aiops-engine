"""Compile the shipped probe and inject socket boundaries without network access."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HARNESS = r'''
#include <arpa/inet.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
static char *payload;
static size_t offset;
static int mode;
static int fake_socket(int a, int b, int c) { (void)a;(void)b;(void)c; return 42; }
static int fake_connect(int fd, const struct sockaddr *a, socklen_t n) {
    const struct sockaddr_in *p = (const struct sockaddr_in *)a;
    (void)fd;(void)n;
    if (ntohs(p->sin_port) != 8000 || ntohl(p->sin_addr.s_addr) != INADDR_LOOPBACK) _exit(9);
    return mode == 1 ? -1 : 0;
}
static ssize_t fake_send(int fd, const void *s, size_t n, int flags) {
    (void)fd;(void)s;(void)flags;
    return mode == 2 ? -1 : (ssize_t)(n > 7 ? 7 : n);
}
static ssize_t fake_recv(int fd, void *s, size_t n, int flags) {
    (void)fd;(void)flags;
    if (mode == 3) return -1;
    if (mode == 4) { for (;;) pause(); }
    size_t remaining = strlen(payload) - offset;
    if (remaining > n) remaining = n;
    if (remaining > 11) remaining = 11;
    memcpy(s, payload+offset, remaining);
    offset += remaining;
    return (ssize_t)remaining;
}
static int fake_close(int fd) { (void)fd; return 0; }
#define socket fake_socket
#define connect fake_connect
#define send fake_send
#define recv fake_recv
#define close fake_close
#define main probe_main
#include "healthcheck.c"
#undef main
int main(int argc, char **argv) {
    (void)argc;
    mode = atoi(argv[1]); payload = argv[2];
    return probe_main();
}
'''


class NativeProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        folder = Path(cls.directory.name)
        (folder / 'healthcheck.c').write_text(Path('scripts/healthcheck.c').read_text())
        (folder / 'harness.c').write_text(HARNESS)
        cls.executable = folder / 'probe'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Os', '-o', str(cls.executable),
                        str(folder / 'harness.c')], check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_success_fragmented_send_and_response(self):
        for version in ('1.0', '1.1'):
            body = '{"status":"ok","mode":"read-only","store":"memory"}'
            result = subprocess.run([str(self.executable), '0', f'HTTP/{version} 200 OK\r\n\r\n{body}'],
                                    capture_output=True, timeout=4)
            self.assertEqual(result.returncode, 0)

    def test_status_payload_oversize_connection_send_read_and_deadline_fail(self):
        for mode, response in ((0, 'HTTP/1.1 503 Nope\r\n\r\n{}'), (0, 'HTTP/1.1 200 OK\r\n\r\n{}'),
                               (0, 'HTTP/1.1 200 OK\r\n\r\n' + 'x'*5000), (0, 'invalid'),
                               (1, ''), (2, ''), (3, ''), (4, '')):
            with self.subTest(mode=mode, response=response[:30]):
                result = subprocess.run([str(self.executable), str(mode), response], capture_output=True, timeout=4)
                self.assertEqual(result.returncode, 1)

    def test_build_context_includes_native_source_and_exec_form_is_single_line(self):
        self.assertIn('!scripts/healthcheck.c', Path('.dockerignore').read_text())
        health = [line for line in Path('Dockerfile').read_text().splitlines() if line.startswith('HEALTHCHECK')]
        self.assertEqual(len(health), 1)
        self.assertTrue(health[0].endswith('CMD ["/usr/local/bin/aiops-healthcheck"]'))
        self.assertIn('--timeout=3s', health[0])
