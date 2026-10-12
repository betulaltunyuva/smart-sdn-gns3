#!/usr/bin/env bash
# Smart SDN (GNS3) - Aşama 7 dashboard başlatıcı
#
# Kullanım:
#   ./start_dashboard.sh                 # http://localhost:8501
#   PORT=8600 ./start_dashboard.sh
#   ADDRESS=0.0.0.0 ./start_dashboard.sh # ağdaki başka cihazlardan erişim
#
# Dashboard yalnızca runtime/state.json'ı okur; controller'ı başlatmaz.
# Controller için: ./start_sdn.sh
set -eu
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -x .venv/bin/streamlit ]; then
    STREAMLIT=.venv/bin/streamlit
elif command -v streamlit >/dev/null 2>&1; then
    STREAMLIT=streamlit
else
    echo "[HATA] streamlit bulunamadı. Kurulum:" >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -r dashboard/requirements.txt" >&2
    exit 1
fi

exec "$STREAMLIT" run dashboard/app.py \
    --server.address "${ADDRESS:-127.0.0.1}" --server.port "${PORT:-8501}"
