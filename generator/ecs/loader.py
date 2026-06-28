"""
generator/ecs/loader.py

Responsável por baixar e manter o spec/ecs/fields.csv atualizado.

Fluxo:
  1. Lê spec/ecs/fields.pin para saber qual versão usar
  2. Se fields.csv não existir ou --force, baixa do GitHub (elastic/ecs)
  3. Valida que o CSV baixado pertence à versão correta
  4. Nunca modifica fields.pin automaticamente — isso é decisão humana

Uso:
  python -m generator.ecs.loader            # baixa se não existir
  python -m generator.ecs.loader --force    # força re-download
  python -m generator.ecs.loader --check    # só verifica, não baixa
"""

import argparse
import csv
import sys
from pathlib import Path

import requests

# ── Caminhos ──────────────────────────────────────────────────────────────────

ROOT       = Path(__file__).resolve().parents[2]
SPEC_ECS   = ROOT / "spec" / "ecs"
PIN_FILE   = SPEC_ECS / "fields.pin"
CSV_FILE   = SPEC_ECS / "fields.csv"

# URL do CSV gerado automaticamente pelo repositório oficial do ECS.
# A tag {version} é substituída pelo conteúdo de fields.pin.
ECS_CSV_URL = (
    "https://raw.githubusercontent.com/elastic/ecs/{version}/generated/csv/fields.csv"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def read_pin() -> str:
    """Lê a versão pinada de spec/ecs/fields.pin."""
    if not PIN_FILE.exists():
        _abort(
            f"Arquivo de versão não encontrado: {PIN_FILE}\n"
            "Crie spec/ecs/fields.pin com o conteúdo da versão desejada.\n"
            "Exemplo: echo '8.11.0' > spec/ecs/fields.pin"
        )
    version = PIN_FILE.read_text().strip()
    if not version:
        _abort(f"{PIN_FILE} está vazio. Coloque a versão ECS desejada (ex: 8.11.0).")
    return version


def download_csv(version: str) -> str:
    """Baixa o fields.csv da versão especificada. Retorna o conteúdo como string."""
    url = ECS_CSV_URL.format(version=version)
    print(f"  → Baixando ECS {version} de {url}")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        _abort(
            f"Falha ao baixar ECS {version}: HTTP {exc.response.status_code}\n"
            f"Verifique se a versão '{version}' existe em https://github.com/elastic/ecs/tags"
        )
    except requests.ConnectionError:
        _abort("Sem conexão com a internet. Não foi possível baixar o fields.csv.")
    return resp.text


def validate_csv_version(content: str, expected_version: str) -> None:
    """
    Garante que o CSV baixado pertence à versão esperada.

    O ECS CSV tem uma coluna 'ECS Version' em cada linha.
    Aceita tanto '8.11.0' quanto '8.11.0-dev' (branch main).
    """
    reader = csv.DictReader(content.splitlines())
    first_row = next(reader, None)
    if first_row is None:
        _abort("fields.csv baixado está vazio.")

    # O nome exato da coluna varia entre versões: 'ECS Version' ou 'ecs_version'
    version_col = next(
        (k for k in first_row if "version" in k.lower()), None
    )
    if not version_col:
        # Se não achar a coluna, avisa mas não aborta — formato pode ter mudado
        print(f"  ⚠  Não foi possível verificar a versão do CSV (coluna não encontrada).")
        return

    csv_version = first_row[version_col].strip()
    # Aceita "8.11.0" e "8.11.0-dev"
    if not csv_version.startswith(expected_version):
        _abort(
            f"Versão do CSV ({csv_version}) não corresponde à versão pinada ({expected_version}).\n"
            "Verifique spec/ecs/fields.pin."
        )
    print(f"  ✓  Versão confirmada: {csv_version}")


def count_fields(content: str) -> int:
    """Retorna o número de campos no CSV (linhas de dados, sem o header)."""
    return sum(1 for line in content.splitlines()[1:] if line.strip())


# ── Ação principal ────────────────────────────────────────────────────────────

def load(force: bool = False, check_only: bool = False) -> Path:
    """
    Garante que spec/ecs/fields.csv existe e está na versão correta.

    Parâmetros
    ----------
    force      : Re-baixa mesmo se o arquivo já existir.
    check_only : Só verifica, não baixa nem escreve nada.

    Retorna o Path do fields.csv.
    """
    SPEC_ECS.mkdir(parents=True, exist_ok=True)
    version = read_pin()
    print(f"[ecs/loader] Versão pinada: {version}")

    if check_only:
        if not CSV_FILE.exists():
            _abort(
                f"spec/ecs/fields.csv não encontrado.\n"
                "Execute sem --check para baixar."
            )
        print(f"  ✓  fields.csv existe ({CSV_FILE.stat().st_size / 1024:.0f} KB)")
        # Valida a versão do arquivo existente
        validate_csv_version(CSV_FILE.read_text(encoding="utf-8"), version)
        return CSV_FILE

    if CSV_FILE.exists() and not force:
        print(f"  ✓  fields.csv já existe — pulando download. Use --force para re-baixar.")
        return CSV_FILE

    content = download_csv(version)
    validate_csv_version(content, version)

    CSV_FILE.write_text(content, encoding="utf-8")
    n = count_fields(content)
    print(f"  ✓  fields.csv salvo: {n} campos ({CSV_FILE.stat().st_size / 1024:.0f} KB)")
    return CSV_FILE


# ── CLI ───────────────────────────────────────────────────────────────────────

def _abort(msg: str) -> None:
    print(f"\n[ERRO] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Baixa e verifica o spec/ecs/fields.csv do repositório oficial ECS."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-baixa mesmo se fields.csv já existir."
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Só verifica se o arquivo existe e está na versão correta. Não baixa nada."
    )
    args = parser.parse_args()
    load(force=args.force, check_only=args.check)


if __name__ == "__main__":
    main()
