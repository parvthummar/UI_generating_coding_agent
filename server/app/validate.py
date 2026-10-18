import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def run_tsc():
    cmd = [
        'node',
        str(REPO / 'sandbox' / 'node_modules' / 'typescript' / 'bin' / 'tsc'),
        '--noEmit',
        '-p',
        str(REPO / 'sandbox' / '.staging' / 'tsconfig.json'),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        return 'Compiler did not finish within 60 seconds'
    output = (result.stdout + result.stderr).strip()
    return output[:4000]
