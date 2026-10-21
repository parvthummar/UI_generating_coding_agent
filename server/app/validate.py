import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STAGING = REPO / 'sandbox' / '.staging'
SANDBOX = REPO / 'sandbox'


def _relative_output(output):
    text = output.replace('\\', '/')
    root = str(REPO).replace('\\', '/')
    if root and not root.endswith('/'):
        root = root + '/'
    # The model knows files as src/..., so drop the staging folder from paths.
    return text.replace(root, '').replace('sandbox/.staging/', '')


def _run(cmd, timeout, cwd):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(cwd))
    except subprocess.TimeoutExpired:
        return 124, 'The command did not finish within ' + str(timeout) + ' seconds'
    except FileNotFoundError:
        return 127, 'Command not found: ' + str(cmd[0])
    output = ((result.stdout or '') + '\n' + (result.stderr or '')).strip()
    return result.returncode, _relative_output(output)


def run_tsc():
    cmd = [
        'node',
        str(SANDBOX / 'node_modules' / 'typescript' / 'bin' / 'tsc'),
        '--noEmit',
        '-p',
        str(STAGING / 'tsconfig.json'),
    ]
    code, output = _run(cmd, 60, REPO)
    if code == 0:
        return ''
    if output == '':
        output = 'TypeScript compiler failed with exit code ' + str(code)
    return output[:4000]


def run_production_build():
    vite_js = SANDBOX / 'node_modules' / 'vite' / 'bin' / 'vite.js'
    config = SANDBOX / 'vite.staging.config.ts'
    if not vite_js.exists():
        return 'Production build failed:\nVite is not installed in sandbox/. Run npm install in sandbox/.'
    cmd = ['node', str(vite_js), 'build', '--config', str(config)]
    code, output = _run(cmd, 90, SANDBOX)
    if code == 0:
        return ''
    if output == '':
        output = 'Vite build failed with exit code ' + str(code)
    return 'Production build failed:\n' + output[:4000]


def run_smoke():
    dist = (STAGING / 'dist').resolve()
    if STAGING.resolve() not in dist.parents:
        return 'Runtime smoke test failed:\nRefusing to test a directory outside staging.'
    script = SANDBOX / 'scripts' / 'smoke.mjs'
    if not (dist / 'index.html').exists():
        return 'Runtime smoke test failed:\nThe staged production build did not produce index.html.'
    if not script.exists():
        return 'Runtime smoke test failed:\nSmoke script is missing.'
    code, output = _run(['node', str(script), str(dist)], 60, SANDBOX)
    if code == 0 and 'SMOKE_OK' in output:
        return ''
    if output == '':
        output = 'Smoke test failed with exit code ' + str(code)
    if output.startswith('Runtime smoke test failed'):
        return output[:4000]
    return 'Runtime smoke test failed:\n' + output[:4000]


def validate_staged():
    errors = run_tsc()
    if errors:
        return 'TypeScript check failed:\n' + errors
    build_errors = run_production_build()
    if build_errors:
        return build_errors
    return run_smoke()


def failure_reason(errors):
    if errors.startswith('TypeScript'):
        return 'compiler'
    if errors.startswith('Production build'):
        return 'build'
    if errors.startswith('Runtime'):
        return 'runtime'
    if errors:
        return 'validation'
    return 'step_limit'
