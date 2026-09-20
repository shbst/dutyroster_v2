#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

app_python="${DUTY_PYTHON:-$HOME/.venvs/duty-planner/bin/python}"
if [[ ! -x "$app_python" ]]; then
    printf '%s\n' 'WSL用の仮想環境が見つかりません。Python 3.12以上で次を実行してください:'
    printf '%s\n' 'python3 -m venv ~/.venvs/duty-planner' '~/.venvs/duty-planner/bin/python -m pip install -r requirements.txt'
    exit 1
fi
"$app_python" -c 'import sys; sys.exit("Python 3.12以上が必要です。") if sys.version_info < (3,12) else None'
app_port="${1:-8765}"
printf '当直ノート: http://localhost:%s （停止はCtrl+C）\n' "$app_port"
printf '%s\n' '接続先確認: /api/bootstrap の api_version が3であることを確認できます。'
exec "$app_python" -m uvicorn app.main:app --host 0.0.0.0 --port "$app_port" --reload --reload-dir app
