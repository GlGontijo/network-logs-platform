"""
generator/vector/vrl.py

Lê os CSVs de mapeamento de um vendor (spec/vendors/<vendor>/*.csv) e gera
os arquivos .vrl correspondentes em build/vector/vendors/<vendor>/.

Pressupostos sobre o pipeline Vector (definidos em vector/consumer/vrl/vendors/<vendor>/parser.vrl):
  - O parser já fez o parse do syslog key=value e populou cada `vendor_field`
    como uma chave de nível raiz do evento: .srcip, .dstip, .action, etc.
  - O router.vrl já garantiu que .type e .subtype existem como strings.
  - Este gerador produz o segundo estágio: vendor_field (raiz) -> ecs_field
    (aninhado), aplicando a transformação declarada na coluna 'transform'.

Uso:
  python -m generator.vector.vrl fortigate
  python -m generator.vector.vrl fortigate --file connection.csv
  python -m generator.vector.vrl --all
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT       = Path(__file__).resolve().parents[2]
SPEC_ROOT  = ROOT / "spec" / "vendors"
BUILD_ROOT = ROOT / "build" / "vector" / "vendors"

# Mapa de retenção por nome de arquivo de spec — usado só para o comentário
# de cabeçalho do .vrl gerado, não afeta a lógica.
RETENTION_BY_FILE = {
    "connection.csv": "12 meses — Registro de CONEXÃO (Marco Civil art. 13)",
    "access.csv":     "6 meses — Registro de ACESSO A APLICAÇÃO (Marco Civil art. 15)",
    "security.csv":   "Política interna — sem obrigação legal direta",
}


# ── Modelo de uma linha do CSV já parseada ────────────────────────────────────

@dataclass
class FieldMapping:
    vendor_field: str
    vendor_type:  str
    fgt_type:     str
    fgt_subtype:  str
    ecs_field:    str
    transform:    str
    required:     bool
    notes:        str


def read_vendor_csv(csv_path: Path) -> list[FieldMapping]:
    """Lê um CSV de vendor e retorna a lista de mapeamentos, ignorando comentários."""
    mappings: list[FieldMapping] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            def _s(key: str) -> str:
                val = row.get(key)
                return val.strip() if val else ""

            vendor_field = _s("vendor_field")
            if not vendor_field or vendor_field.startswith("#"):
                continue

            mappings.append(FieldMapping(
                vendor_field = vendor_field,
                vendor_type  = _s("vendor_type"),
                fgt_type     = _s("fgt_type"),
                fgt_subtype  = _s("fgt_subtype"),
                ecs_field    = _s("ecs_field"),
                transform    = _s("transform"),
                required     = _s("required").lower() == "true",
                notes        = _s("notes"),
            ))
    return mappings


# ── Tradução de 'transform' para código VRL ───────────────────────────────────
#
# Cada função recebe o caminho de origem (ex: ".srcip") e o caminho de
# destino (ex: ".source.ip") e devolve uma lista de linhas VRL.
#
# Convenção: cada bloco testa a existência/validade do campo de origem antes
# de escrever no destino, para não popular campos ECS com null/"N/A"/"".

def _vrl_copy(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    {dst} = {src}",
        f"}}",
    ]


def _vrl_to_int(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    {dst}, err = to_int({src})",
        f'    if err != null {{ log("VRL to_int falhou para {fm.vendor_field}: " + err, level: "warn") }}',
        f"}}",
    ]


def _vrl_to_float(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    {dst}, err = to_float({src})",
        f'    if err != null {{ log("VRL to_float falhou para {fm.vendor_field}: " + err, level: "warn") }}',
        f"}}",
    ]


def _vrl_to_bool(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    {dst}, err = to_bool({src})",
        f'    if err != null {{ log("VRL to_bool falhou para {fm.vendor_field}: " + err, level: "warn") }}',
        f"}}",
    ]


def _vrl_ip_validate(src: str, dst: str, fm: FieldMapping) -> list[str]:
    # FortiOS costuma usar "N/A" ou "0.0.0.0" como placeholder de "sem IP".
    # Só grava o campo ECS quando o valor é uma string não-vazia e diferente
    # desses placeholders. A validação real de formato IP fica a cargo do
    # mapping do OpenSearch (tipo `ip`), que rejeita valores inválidos no índice.
    return [
        f"if exists({src}) {{",
        f"    _val = to_string({src}) ?? \"\"",
        f'    if _val != "" && _val != "N/A" && _val != "0.0.0.0" {{',
        f"        {dst} = _val",
        f"    }}",
        f"}}",
    ]


def _vrl_to_lowercase(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    {dst} = downcase(to_string({src}) ?? \"\")",
        f"}}",
    ]


def _vrl_to_uppercase(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    {dst} = upcase(to_string({src}) ?? \"\")",
        f"}}",
    ]


def _vrl_trim(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    {dst} = strip_whitespace(to_string({src}) ?? \"\")",
        f"}}",
    ]


def _vrl_epoch_to_iso(src: str, dst: str, fm: FieldMapping) -> list[str]:
    # Uso exclusivo para campos que já são epoch numérico (ex: 'eventtime').
    # NÃO usar para os campos 'date' ou 'time' do FortiOS — esses são strings
    # de calendário/relógio, não timestamps Unix. Ver _vrl_date_time_to_iso.
    return [
        f"if exists({src}) {{",
        f"    _raw, err = to_int({src})",
        f"    if err == null {{",
        f"        _secs = _raw",
        f"        if _raw > 100000000000 {{ _secs = _raw / 1000000000 }}",  # ns -> s
        f"        {dst} = from_unix_timestamp!(_secs, unit: \"seconds\")",
        f"    }}",
        f"}}",
    ]


def _vrl_date_time_to_iso(src: str, dst: str, fm: FieldMapping) -> list[str]:
    # Combina os campos STRING '.date' ("2023-08-10") e '.time' ("15:02:25")
    # do FortiOS em um timestamp ISO 8601 real. Este handler é acionado pela
    # linha do CSV que mapeia 'time' -> '@timestamp'; ele lê '.date' e '.time'
    # diretamente (não usa `src`/`dst` genéricos porque precisa dos dois campos
    # ao mesmo tempo). O parâmetro `dst` ainda é respeitado como destino.
    return [
        f"if exists(.date) && exists(.time) {{",
        f'    _combined = (to_string(.date) ?? "") + " " + (to_string(.time) ?? "")',
        f'    _ts, err = parse_timestamp(_combined, format: "%Y-%m-%d %H:%M:%S")',
        f"    if err == null {{",
        f"        {dst} = _ts",
        f"    }} else {{",
        f'        log("VRL parse_timestamp falhou para date+time: " + err, level: "warn")',
        f"    }}",
        f"}}",
    ]


def _vrl_ms_to_ns(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    _ms, err = to_int({src})",
        f"    if err == null {{ {dst} = _ms * 1000000 }}",
        f"}}",
    ]


def _vrl_s_to_ns(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    _s, err = to_int({src})",
        f"    if err == null {{ {dst} = _s * 1000000000 }}",
        f"}}",
    ]


def _vrl_bytes_to_int(src: str, dst: str, fm: FieldMapping) -> list[str]:
    return [
        f"if exists({src}) {{",
        f"    _clean = replace(to_string({src}) ?? \"\", r'[^0-9]', \"\")",
        f"    {dst}, err = to_int(_clean)",
        f'    if err != null {{ log("VRL bytes_to_int falhou para {fm.vendor_field}: " + err, level: "warn") }}',
        f"}}",
    ]


def _vrl_conditional(src: str, dst: str, fm: FieldMapping) -> list[str]:
    # Padrão comum detectado nos CSVs do FortiGate: campos onde a única
    # condição é "descartar quando o valor for 'N/A' (ou vazio)". Isso cobre
    # a maioria dos casos de 'user', 'group', 'reason' etc. Resolvido aqui
    # automaticamente para não gerar TODO desnecessário.
    notes_lower = fm.notes.lower()
    mentions_empty_or_na = "n/a" in notes_lower or "vazio" in notes_lower or "empty" in notes_lower
    is_na_discard_pattern = (
        mentions_empty_or_na
        and "descart" in notes_lower
        and "extrair" not in notes_lower  # authproto tem lógica extra, não é só N/A
    )

    if is_na_discard_pattern:
        return [
            f"if exists({src}) {{",
            f"    _val = to_string({src}) ?? \"\"",
            f'    if _val != "" && _val != "N/A" {{',
            f"        {dst} = _val",
            f"    }}",
            f"}}",
        ]

    # Casos com lógica de negócio genuína (ex: action/status -> event.outcome,
    # que exige uma tabela de valores diferente por subtype; ou authproto, que
    # exige extrair a parte antes do parêntese). Ficam como TODO explícito.
    note = fm.notes.replace('"', "'") if fm.notes else "sem nota — revisar manualmente"
    return [
        f"# TODO(conditional): '{fm.vendor_field}' -> '{fm.ecs_field}'",
        f"# Regra: {note}",
        f"# Implementar em vector/consumer/vrl/vendors/fortigate/custom/ e importar aqui.",
        f'if exists({src}) {{ log("Campo condicional não implementado: {fm.vendor_field}", level: "debug") }}',
    ]


def _vrl_derived(src: str, dst: str, fm: FieldMapping) -> list[str]:
    note = fm.notes.replace('"', "'") if fm.notes else "campo derivado — ver notes no CSV"
    return [
        f"# DERIVED: '{fm.ecs_field}' não vem do payload — {note}",
        f"# Preencher via enrichment table do Vector (transform 'enrichment_tables' ou 'remap' downstream).",
    ]


def _vrl_discard(src: str, dst: str, fm: FieldMapping) -> list[str]:
    note = fm.notes.replace('"', "'") if fm.notes else ""
    return [f"# DISCARD: '{fm.vendor_field}' intencionalmente não mapeado. {note}".rstrip()]


TRANSFORM_HANDLERS = {
    "copy":          _vrl_copy,
    "to_int":        _vrl_to_int,
    "to_float":      _vrl_to_float,
    "to_bool":       _vrl_to_bool,
    "ip_validate":   _vrl_ip_validate,
    "to_lowercase":  _vrl_to_lowercase,
    "to_uppercase":  _vrl_to_uppercase,
    "trim":          _vrl_trim,
    "epoch_to_iso":  _vrl_epoch_to_iso,
    "date_time_to_iso": _vrl_date_time_to_iso,
    "ms_to_ns":      _vrl_ms_to_ns,
    "s_to_ns":       _vrl_s_to_ns,
    "bytes_to_int":  _vrl_bytes_to_int,
    "conditional":   _vrl_conditional,
    "derived":       _vrl_derived,
    "discard":       _vrl_discard,
}


def _ecs_path(ecs_field: str) -> str:
    """Converte 'source.ip' em '.source.ip' e '@timestamp' em '.\"@timestamp\"'."""
    if ecs_field == "@timestamp":
        return '.\"@timestamp\"'
    return "." + ecs_field


def _vendor_path(vendor_field: str) -> str:
    """Converte 'srcip' em '.srcip'. Campos _enrichment_* não têm origem própria."""
    return "." + vendor_field


def render_field_mapping(fm: FieldMapping) -> list[str]:
    """Gera as linhas VRL para uma única linha do CSV."""
    handler = TRANSFORM_HANDLERS.get(fm.transform)
    if handler is None:
        return [f"# ERRO: transform desconhecido '{fm.transform}' para '{fm.vendor_field}' — pulei esta linha"]

    src = _vendor_path(fm.vendor_field)
    dst = _ecs_path(fm.ecs_field)
    return handler(src, dst, fm)


# ── Agrupamento e geração de arquivo ──────────────────────────────────────────

def group_by_subtype(mappings: list[FieldMapping]) -> dict[tuple[str, str], list[FieldMapping]]:
    """Agrupa mapeamentos por (fgt_type, fgt_subtype), preservando a ordem de aparição."""
    groups: dict[tuple[str, str], list[FieldMapping]] = {}
    for fm in mappings:
        key = (fm.fgt_type, fm.fgt_subtype)
        groups.setdefault(key, []).append(fm)
    return groups


def render_subtype_block(fgt_type: str, fgt_subtype: str, mappings: list[FieldMapping]) -> str:
    """Gera o bloco 'if .type == X && .subtype == Y { ... }' para um subtype."""
    subtype_cond = f'.subtype == "{fgt_subtype}"' if fgt_subtype != "*" else "true"
    lines = [
        f'if .type == "{fgt_type}" && {subtype_cond} {{',
    ]
    for fm in mappings:
        for vrl_line in render_field_mapping(fm):
            lines.append(f"    {vrl_line}")
        lines.append("")
    lines.append("}")
    return "\n".join(lines)


def generate_vrl_file(csv_path: Path, vendor: str) -> str:
    """Gera o conteúdo completo de um arquivo .vrl a partir de um CSV de vendor."""
    mappings = read_vendor_csv(csv_path)
    groups   = group_by_subtype(mappings)
    retention_note = RETENTION_BY_FILE.get(csv_path.name, "retenção não especificada")

    header = [
        "##############################################################################",
        f"# GERADO AUTOMATICAMENTE por generator/vector/vrl.py",
        f"# Fonte: spec/vendors/{vendor}/{csv_path.name}",
        f"# NÃO EDITE ESTE ARQUIVO À MÃO — edite o CSV de origem e rode:",
        f"#   docker compose run builder",
        f"#",
        f"# Classe de retenção: {retention_note}",
        "##############################################################################",
        "",
    ]

    blocks = []
    for (fgt_type, fgt_subtype), group_mappings in groups.items():
        blocks.append(f"# ─── {vendor} · type={fgt_type} subtype={fgt_subtype} " + "─" * 20)
        blocks.append(render_subtype_block(fgt_type, fgt_subtype, group_mappings))
        blocks.append("")

    return "\n".join(header + blocks)


def generate_for_vendor(vendor: str, only_file: Optional[str] = None) -> list[Path]:
    """
    Gera todos os .vrl de um vendor a partir de spec/vendors/<vendor>/*.csv.
    Retorna a lista de Paths gerados.
    """
    vendor_spec_dir  = SPEC_ROOT / vendor
    vendor_build_dir = BUILD_ROOT / vendor
    vendor_build_dir.mkdir(parents=True, exist_ok=True)

    if not vendor_spec_dir.exists():
        raise FileNotFoundError(f"spec/vendors/{vendor}/ não encontrado")

    csv_files = sorted(vendor_spec_dir.glob("*.csv"))
    if only_file:
        csv_files = [f for f in csv_files if f.name == only_file]
        if not csv_files:
            raise FileNotFoundError(f"{only_file} não encontrado em spec/vendors/{vendor}/")

    generated: list[Path] = []
    for csv_path in csv_files:
        vrl_content = generate_vrl_file(csv_path, vendor)
        vrl_path = vendor_build_dir / (csv_path.stem + ".vrl")
        vrl_path.write_text(vrl_content, encoding="utf-8")
        generated.append(vrl_path)
        n_mappings = len(read_vendor_csv(csv_path))
        print(f"  ✓  {csv_path.name} → {vrl_path.relative_to(ROOT)} ({n_mappings} campos)")

    return generated


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera arquivos .vrl a partir dos CSVs de mapeamento de vendor."
    )
    parser.add_argument("vendor", nargs="?", help="Nome do vendor (ex: fortigate)")
    parser.add_argument("--file", help="Gerar apenas um CSV específico (ex: connection.csv)")
    parser.add_argument("--all", action="store_true", help="Gerar para todos os vendors em spec/vendors/")
    args = parser.parse_args()

    if args.all:
        vendors = sorted(p.name for p in SPEC_ROOT.iterdir() if p.is_dir())
    elif args.vendor:
        vendors = [args.vendor]
    else:
        parser.error("Especifique um vendor ou use --all")
        return

    total = 0
    for vendor in vendors:
        print(f"[vrl] Gerando para vendor '{vendor}'...")
        generated = generate_for_vendor(vendor, only_file=args.file)
        total += len(generated)

    print(f"\n✓  {total} arquivo(s) .vrl gerado(s) em build/vector/vendors/")


if __name__ == "__main__":
    main()
