#!/usr/bin/env python3
"""Baixa/atualiza o banco GeoLite2-City da MaxMind usado pela detecção de
país/estado do ranking (app/core/geoip.py).

Uso único (setup inicial) ou re-execução periódica (a MaxMind atualiza o
GeoLite2 algumas vezes por mês; num app com poucos usuários, rodar isso a
cada poucos meses já é suficiente -- não precisa de agendamento automático).

Precisa de uma conta gratuita em https://www.maxmind.com/en/geolite2/signup
-- depois de criar, gere uma "license key" em
Minha conta > Gerenciar chaves de licença, e exporte:

    export GEOIP_ACCOUNT_ID=<seu account id>
    export GEOIP_LICENSE_KEY=<sua license key>

Depois rode: python scripts/download_geoip_db.py
"""

import os
import sys
import tarfile
import tempfile

import httpx

GEOIP_ACCOUNT_ID = os.environ.get("GEOIP_ACCOUNT_ID")
GEOIP_LICENSE_KEY = os.environ.get("GEOIP_LICENSE_KEY")
GEOIP_DB_PATH = os.environ.get("GEOIP_DB_PATH", "geoip/GeoLite2-City.mmdb")

DOWNLOAD_URL = "https://download.maxmind.com/geoip/databases/GeoLite2-City/download?suffix=tar.gz"
REQUEST_TIMEOUT = 120


def main() -> None:
    if not GEOIP_LICENSE_KEY:
        print("GEOIP_LICENSE_KEY não configurada -- crie uma conta gratuita em " "maxmind.com/en/geolite2/signup e gere uma license key.")
        sys.exit(1)

    auth = (GEOIP_ACCOUNT_ID, GEOIP_LICENSE_KEY) if GEOIP_ACCOUNT_ID else None
    params = {} if GEOIP_ACCOUNT_ID else {"license_key": GEOIP_LICENSE_KEY}

    response = httpx.get(DOWNLOAD_URL, auth=auth, params=params, timeout=REQUEST_TIMEOUT, follow_redirects=True)
    if response.status_code != 200:
        print(f"Download falhou: {response.status_code} {response.text[:500]}")
        sys.exit(1)

    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp_archive:
        tmp_archive.write(response.content)
        tmp_archive.flush()

        with tarfile.open(tmp_archive.name, "r:gz") as archive:
            mmdb_members = [m for m in archive.getmembers() if m.name.endswith(".mmdb")]
            if not mmdb_members:
                print("Arquivo .mmdb não encontrado dentro do pacote baixado.")
                sys.exit(1)

            os.makedirs(os.path.dirname(GEOIP_DB_PATH) or ".", exist_ok=True)
            with archive.extractfile(mmdb_members[0]) as src, open(GEOIP_DB_PATH, "wb") as dst:
                dst.write(src.read())

    print(f"GeoLite2-City salvo em {GEOIP_DB_PATH}")


if __name__ == "__main__":
    main()
