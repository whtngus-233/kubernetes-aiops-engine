#!/usr/bin/env bash
# HOST only. Mutates exactly aiops-final-health and the aiops-engine:1.0.0 image.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec python3 - <<'PY'
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
import urllib.error
from scripts.host_runtime import locate_cgroup, snapshot, interval_cpu, lifecycle, cpu_sources

NAME = 'aiops-final-health'
IMAGE = 'aiops-engine:1.0.0'
results = []

def report(status, label, detail=''):
    results.append(status)
    print(f'{status}: {label}' + (f' — {detail}' if detail else ''), flush=True)

def run(args, seconds=20):
    # No shell expansion, no unbounded exec/auth-plugin waits, no secret output.
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        out, err = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise RuntimeError('command deadline exceeded')
    if process.returncode:
        raise RuntimeError(f'{args[0]} failed (exit {process.returncode}); private output suppressed')
    return out.strip()

def inspect(target=NAME):
    return json.loads(run(['docker', 'inspect', target]))[0]

def http(url, seconds=3):
    start = time.monotonic()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=seconds) as response:
        if response.status != 200:
            raise RuntimeError('HTTP status is not 200')
        body = response.read(4097)
    if len(body) > 4096:
        raise RuntimeError('response exceeds bound')
    return time.monotonic() - start, body

# Fail before container replacement if required HOST tools/daemon are unavailable.
for executable in ('docker', 'python3'):
    if not shutil.which(executable):
        report('NOT AVAILABLE', executable)
        print('SCRIPT EXIT CODE: 2', flush=True)
        sys.exit(2)
try:
    run(['docker', 'version', '--format', '{{.Server.Version}}'], 15)
    run(['docker', 'ps', '-q'], 15)
except Exception as error:
    report('NOT AVAILABLE', 'Docker daemon', str(error))
    print('SCRIPT EXIT CODE: 2', flush=True)
    sys.exit(2)
before = {}
try:
    # Snapshot identities to prove no other container was removed/restarted by us.
    ids = run(['docker', 'ps', '-aq', '--no-trunc']).splitlines()
    before = {}
    old = None
    for cid in ids:
        item = inspect(cid)
        if item['Name'] == '/' + NAME:
            old = item
        else:
            before[cid] = (item['Name'], item['State']['StartedAt'], item['State']['Status'])
    if old and (old['Config']['Image'] != IMAGE or
                any((old['Config'].get('Labels') or {}).get(k, '') for k in
                    ('com.docker.compose.project', 'com.docker.swarm.service.name'))):
        raise RuntimeError('target name belongs to an unexpected image/managed service; replacement refused')
    run(['docker', 'build', '-t', IMAGE, '.'], 900)
    report('PASS', 'Docker image build', IMAGE)
    image = inspect(IMAGE)
    expected_probe = ['CMD', '/usr/local/bin/aiops-healthcheck']
    actual_probe = image['Config'].get('Healthcheck', {}).get('Test')
    report('PASS' if actual_probe == expected_probe else 'FAIL', 'image healthcheck exec form', repr(actual_probe))
    if actual_probe != expected_probe:
        raise RuntimeError('HEALTHCHECK parser/image mismatch; refusing replacement')
    if old:
        # Exact previously inspected ID prevents replacing a raced-in container.
        run(['docker', 'rm', '-f', old['Id']], 30)
    cid = run(['docker', 'run', '-d', '--name', NAME, '--init', '--read-only',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--label', 'aiops.validation=final-host',
               '-p', '127.0.0.1::8000', '-e', 'AIOPS_ALLOWED_NAMESPACES=default', IMAGE], 30)
    item = inspect()
    if item['Id'] != cid or not item['State']['Running']:
        raise RuntimeError('validation container is not running')
    report('PASS', 'container running', NAME)
    report('PASS' if item['Config'].get('Healthcheck', {}).get('Test') == expected_probe else 'FAIL',
           'container healthcheck matches image', repr(item['Config'].get('Healthcheck', {}).get('Test')))
    port = item['NetworkSettings']['Ports']['8000/tcp'][0]['HostPort']
    url = f'http://127.0.0.1:{port}/health'
    # Random loopback port avoids taking another service's port 8000.
    deadline = time.monotonic() + 120
    healthy = False
    while time.monotonic() < deadline:
        item = inspect()
        if not item['State']['Running']:
            break
        if item['State'].get('Health', {}).get('Status') == 'healthy':
            healthy = True
            break
        time.sleep(2)
    report('PASS' if healthy else 'FAIL', 'Docker health bounded wait',
           item['State'].get('Health', {}).get('Status', 'missing'))
    if not healthy:
        # Sanitized timing/exit evidence only, no potentially sensitive log text.
        for entry in item['State'].get('Health', {}).get('Log', []):
            from app.security import sanitize
            print('healthcheck:', entry.get('Start'), entry.get('End'), 'exit', entry.get('ExitCode'),
                  'output', json.dumps(sanitize(entry.get('Output', ''), limit=512)))
    cgroup = locate_cgroup(item['State']['Pid'])
    baseline = snapshot(cgroup)
    # Avoid choosing the transient probe as the application baseline.
    for attempt in range(6):
        if not any(t['name'] in ('aiops-healthche', 'runc:[2:INIT]') for t in baseline['tasks'].values()):
            break
        time.sleep(.5)
        baseline = snapshot(cgroup)
    if len(baseline['tasks']) != 2 or any(t['name'] not in ('docker-init', 'uvicorn') for t in baseline['tasks'].values()):
        raise RuntimeError('unexpected idle baseline (expected init + single uvicorn task)')
    print('baseline tasks:', baseline['tasks'], flush=True)
    previous = baseline
    lifecycle_ok = True
    first_seen = {}
    latencies, cpus, pids, zombies = [], [], [], []
    sampling_ok = True
    for index in range(12):
        try:
            latency, body = http(url)
            if json.loads(body) != {'status': 'ok', 'mode': 'read-only', 'store': 'memory'}:
                raise RuntimeError('health payload mismatch')
            latencies.append(latency)
            window_start = previous
            observed_pids, observed_zombies = [], []
            last_tick = previous
            for tick in range(10):
                time.sleep(.5)
                current = snapshot(cgroup)
                valid, extras = lifecycle(baseline, current, first_seen)
                lifecycle_ok &= valid
                observed_pids.append(current['pids'])
                observed_zombies.append(sum(t['state'] == 'Z' for t in current['tasks'].values()))
                # Task CPU ticks, identities and monotonic timestamps identify sources;
                # no argv/environment/credentials are read or printed.
                print('accounting:', json.dumps(current), 'cpu sources:', json.dumps(cpu_sources(last_tick, current, os.sysconf('SC_CLK_TCK'))), 'temporary tasks:', json.dumps(extras), flush=True)
                last_tick = current
            cpu = interval_cpu(window_start, current)
            previous = current
            cpus.append(cpu); pids.append(max(observed_pids)); zombies.append(max(observed_zombies))
            print(f'sample {index+1}: health={latency:.4f}s CPU-window={cpu:.2f}% PIDS-max={pids[-1]} zombies={zombies[-1]}', flush=True)
            for entry in inspect()['State'].get('Health', {}).get('Log', []):
                print('probe interval:', entry.get('Start'), entry.get('End'), 'exit', entry.get('ExitCode'), flush=True)
        except Exception as error:
            sampling_ok = False
            report('FAIL', f'runtime sample {index+1}', str(error))
    complete = sampling_ok and len(latencies) == len(cpus) == len(pids) == len(zombies) == 12
    report('PASS' if complete else 'FAIL', 'host /health HTTP 200', url)
    report('PASS' if complete and max(latencies) < 2 else 'FAIL', 'health latency',
           f'max={max(latencies):.4f}s mean={statistics.mean(latencies):.4f}s; limit <2s' if latencies else 'no samples')
    # Idle smoke thresholds are explicit acceptance criteria, not resource caps.
    mean_cpu = interval_cpu(baseline, previous)
    report('PASS' if complete and max(cpus) < 50 and mean_cpu < 10 else 'FAIL',
           'idle CPU stability', f'cumulative ~5s windows={cpus}; max <50%, weighted mean={mean_cpu:.2f}% <10%; includes probes and host requests')
    final_runtime = snapshot(cgroup)
    baseline_restored = all(
        pid in final_runtime['tasks']
        and final_runtime['tasks'][pid]['start'] == task['start']
        for pid, task in baseline['tasks'].items()
    )
    pids_ok = (
        complete
        and max(pids, default=0) <= 32
        and not any(zombies)
        and baseline_restored
    )
    report('PASS' if pids_ok else 'FAIL',
           'idle PIDS stability',
           f'samples={pids}; baseline identities retained={baseline_restored}; '
           f'temporary native probe/runc tasks allowed; PIDS <=32; zombies=0')
    report('PASS' if complete and not any(zombies) else 'FAIL', 'repeated zombie/defunct checks', str(zombies))
    final = inspect()
    report('PASS' if final['State']['Running'] and final['State'].get('Health', {}).get('Status') == 'healthy'
           else 'FAIL', 'Docker health after sampling')
except Exception as error:
    report('FAIL', 'Docker validation', str(error))

if before:
    unchanged = True
    for cid, expected in before.items():
        try:
            other = inspect(cid)
            unchanged &= (other['Name'], other['State']['StartedAt'], other['State']['Status']) == expected
        except Exception:
            unchanged = False
    report('PASS' if unchanged else 'FAIL', 'other container identities/start times/states unchanged')

for label, url in (('Prometheus live readiness', 'http://127.0.0.1:9090/-/ready'),
                   ('Loki live readiness', 'http://127.0.0.1:3300/ready')):
    try:
        elapsed, _ = http(url, 5)
        report('PASS', label, f'HTTP 200, {elapsed:.4f}s')
    except urllib.error.HTTPError as error:
        # Read only the known readiness endpoint, bounded and escaped. Redact secrets.
        from app.security import sanitize
        try:
            body = sanitize(error.read(1024).decode('utf-8', errors='replace'))
        except Exception:
            body = '[readiness body unavailable]'
        finally:
            error.close()
        report('NOT AVAILABLE', label, f'HTTP {error.code}; readiness body={json.dumps(body)}')
    except Exception as error:
        report('NOT AVAILABLE', label, f'{type(error).__name__}; external readiness unavailable')

if not shutil.which('kubectl'):
    report('NOT AVAILABLE', 'Kubernetes READ-ONLY connectivity', 'kubectl missing')
else:
    try:
        # config view/current-context are local; the only remote operation is GET pods.
        context = run(['kubectl', 'config', 'current-context'], 5)
        if not context:
            report('NOT CONFIGURED', 'Kubernetes READ-ONLY connectivity', 'no current context')
        else:
            namespace = os.environ.get('AIOPS_VALIDATION_NAMESPACE', 'default')
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', namespace):
                raise RuntimeError('invalid validation namespace')
            data = json.loads(run(['kubectl', '--request-timeout=8s', 'get', 'pods',
                                   '-n', namespace, '--chunk-size=100', '-o', 'json'], 20))
            if data.get('kind') not in ('PodList', 'List') or not isinstance(data.get('items'), list):
                raise RuntimeError('unexpected Kubernetes response')
            report('PASS', 'Kubernetes READ-ONLY connectivity', f'pods list namespace={namespace}')
    except Exception as error:
        # Empty config is distinct from configured API/auth/network failure.
        try:
            configured = bool(json.loads(run(['kubectl', 'config', 'view', '-o', 'json'], 5)).get('contexts'))
        except Exception:
            configured = True
        report('NOT AVAILABLE' if configured else 'NOT CONFIGURED', 'Kubernetes READ-ONLY connectivity', str(error))

print('Validation container is retained for inspection. No Kubernetes writes, commit, push or tag.', flush=True)
if 'FAIL' in results:
    report('FAIL', 'overall HOST validation')
    print('SCRIPT EXIT CODE: 1', flush=True)
    sys.exit(1)
if any(s in results for s in ('NOT AVAILABLE', 'NOT CONFIGURED')):
    report('NOT AVAILABLE', 'overall HOST validation', 'required evidence incomplete')
    print('SCRIPT EXIT CODE: 2', flush=True)
    sys.exit(2)
report('PASS', 'overall HOST validation')
print('SCRIPT EXIT CODE: 0', flush=True)
sys.exit(0)
PY
