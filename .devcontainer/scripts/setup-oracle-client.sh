#!/usr/bin/env bash
set -euo pipefail

# Instala sqlplus y sqlldr dentro del devcontainer a partir de ZIPs
# oficiales de Oracle Instant Client (basic/basiclite + sqlplus + tools).

if [[ "$#" -ne 3 ]]; then
  echo "Uso:"
  echo "  setup-oracle-client <basic_or_basiclite.zip> <sqlplus.zip> <tools.zip>"
  exit 1
fi

BASIC_ZIP="$1"
SQLPLUS_ZIP="$2"
TOOLS_ZIP="$3"

for f in "$BASIC_ZIP" "$SQLPLUS_ZIP" "$TOOLS_ZIP"; do
  if [[ ! -f "$f" ]]; then
    echo "No existe: $f" >&2
    exit 1
  fi
done

sudo mkdir -p /opt/oracle
sudo rm -rf /opt/oracle/instantclient_*
sudo unzip -q "$BASIC_ZIP" -d /opt/oracle
sudo unzip -q "$SQLPLUS_ZIP" -d /opt/oracle
sudo unzip -q "$TOOLS_ZIP" -d /opt/oracle

IC_DIR="$(ls -d /opt/oracle/instantclient_* | head -n 1)"
if [[ -z "$IC_DIR" ]]; then
  echo "No se encontro carpeta instantclient_* en /opt/oracle" >&2
  exit 1
fi

sudo ln -sf "${IC_DIR}/sqlplus" /usr/local/bin/sqlplus
sudo ln -sf "${IC_DIR}/sqlldr" /usr/local/bin/sqlldr

PROFILE_FILE="/etc/profile.d/oracle-instantclient.sh"
echo "export LD_LIBRARY_PATH=${IC_DIR}:\${LD_LIBRARY_PATH:-}" | sudo tee "$PROFILE_FILE" >/dev/null
echo "export PATH=${IC_DIR}:\${PATH}" | sudo tee -a "$PROFILE_FILE" >/dev/null
source "$PROFILE_FILE"

echo "Oracle client instalado."
echo "Verifica con: sqlplus -v && sqlldr -help | head"
