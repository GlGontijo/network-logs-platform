"""
generator/ecs/validator.py

Valida os CSVs de vendor (spec/vendors/*/*.csv) contra o ECSRegistry.

Para cada linha do CSV de vendor, verifica:
  1. Coluna 'ecs_field' existe e não está vazia
  2. O campo ECS existe no registry (nome correto)
  3. O tipo do vendor é compatível com o tipo ECS
  4. A transformação declarada em 'transform' é conhecida
  5. Colunas obrigatórias estão presentes no arquivo

Retorna um ValidationReport com todos os erros e warnings encontrados,
sem abortar no primeiro problema — o objetivo é mostrar tudo de uma vez.

Uso:
  from generator.ecs.validator import VendorValidator
  from generator.ecs.registry  import ECSRegistry

  reg       = ECSRegistry.load()
  validator = VendorValidator(reg)
  report    = validator.validate_file(Path("spec/vendors/fortigate/connection.csv"))

  if report.has_errors:
      report.print()
      sys.exit(1)
"""

import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from generator.ecs.registry import ECSRegistry, ECSFieldNotFoundError, ECSTypeError

# ── Transformações conhecidas ─────────────────────────────────────────────────
# O gerador VRL usa esses identificadores para saber qual código emitir.

KNOWN_TRANSFORMS: set[str] = {
    "copy",           # copia o valor sem alteração
    "to_int",         # parse para inteiro
    "to_float",       # parse para float
    "to_bool",        # parse para boolean
    "ip_validate",    # valida IP e descarta "N/A" (padrão FortiOS)
    "to_lowercase",   # converte string para minúsculas
    "to_uppercase",   # converte string para maiúsculas
    "trim",           # remove espaços extras
    "epoch_to_iso",   # timestamp Unix → ISO 8601
    "ms_to_ns",       # milissegundos → nanosegundos (para event.duration)
    "s_to_ns",        # segundos → nanosegundos (para event.duration)
    "bytes_to_int",   # string como "1024B" → inteiro
    "conditional",    # lógica condicional — requer coluna 'notes' explicando
    "derived",        # campo calculado — não existe no vendor, gerado pelo VRL
    "discard",        # campo existe no vendor mas NÃO deve ser mapeado
}

# ── Colunas obrigatórias no CSV de vendor ─────────────────────────────────────

REQUIRED_COLUMNS = {
    "vendor_field",
    "vendor_type",
    "ecs_field",
    "transform",
    "required",
}

# ── Modelos de resultado ──────────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    severity: str      # "ERROR" | "WARNING"
    row:      int      # número da linha no CSV (1-based, incluindo header)
    column:   str      # coluna onde o problema foi detectado
    message:  str
    hint:     str = ""

    def __str__(self) -> str:
        loc = f"linha {self.row}, coluna '{self.column}'"
        hint = f"\n    → {self.hint}" if self.hint else ""
        return f"  [{self.severity}] {loc}: {self.message}{hint}"


@dataclass
class ValidationReport:
    csv_path: Path
    issues:   list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "WARNING"]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def print(self, file=sys.stdout) -> None:
        status = "✗ FALHOU" if self.has_errors else "✓ OK"
        print(f"\n[validator] {self.csv_path.name} — {status}", file=file)
        print(f"  {len(self.errors)} erro(s), {len(self.warnings)} aviso(s)", file=file)
        for issue in self.issues:
            print(str(issue), file=file)

    def add_error(self, row: int, column: str, message: str, hint: str = "") -> None:
        self.issues.append(ValidationIssue("ERROR", row, column, message, hint))

    def add_warning(self, row: int, column: str, message: str, hint: str = "") -> None:
        self.issues.append(ValidationIssue("WARNING", row, column, message, hint))


# ── Validator ─────────────────────────────────────────────────────────────────

class VendorValidator:
    """
    Valida CSVs de vendor contra o ECSRegistry.

    Instanciar uma vez, reutilizar para múltiplos arquivos.
    """

    def __init__(self, registry: ECSRegistry) -> None:
        self._reg = registry

    def validate_file(self, csv_path: Path) -> ValidationReport:
        """
        Valida um arquivo CSV de vendor completo.
        Retorna um ValidationReport com todos os problemas encontrados.
        """
        report = ValidationReport(csv_path=csv_path)

        if not csv_path.exists():
            report.add_error(0, "arquivo", f"Arquivo não encontrado: {csv_path}")
            return report

        with csv_path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []

            # 1. Verifica colunas obrigatórias
            self._check_columns(fieldnames, report)
            if report.has_errors:
                # Sem colunas, não adianta continuar
                return report

            # 2. Valida cada linha
            for row_idx, row in enumerate(reader, start=2):  # +2: 1-based + header
                self._validate_row(row, row_idx, report)

        return report

    def validate_directory(self, vendors_dir: Path) -> list[ValidationReport]:
        """
        Valida todos os CSVs em spec/vendors/<vendor>/*.csv.
        Retorna uma lista de ValidationReport, um por arquivo.
        """
        reports = []
        for csv_file in sorted(vendors_dir.rglob("*.csv")):
            reports.append(self.validate_file(csv_file))
        return reports

    # ── Validações internas ───────────────────────────────────────────────────

    def _check_columns(self, fieldnames: list[str], report: ValidationReport) -> None:
        missing = REQUIRED_COLUMNS - set(fieldnames)
        for col in sorted(missing):
            report.add_error(
                row=1, column=col,
                message=f"Coluna obrigatória ausente: '{col}'",
                hint=f"Adicione a coluna '{col}' ao cabeçalho do CSV."
            )

    def _validate_row(self, row: dict, row_idx: int, report: ValidationReport) -> None:
        vendor_field = row.get("vendor_field", "").strip()
        vendor_type  = row.get("vendor_type",  "").strip()
        ecs_field    = row.get("ecs_field",    "").strip()
        transform    = row.get("transform",    "").strip()
        required_str = row.get("required",     "").strip().lower()

        # Linhas em branco ou comentadas com '#' são ignoradas
        if not vendor_field or vendor_field.startswith("#"):
            return

        # ── ecs_field vazio ───────────────────────────────────────────────────
        if not ecs_field:
            report.add_error(
                row=row_idx, column="ecs_field",
                message=f"'{vendor_field}': coluna 'ecs_field' está vazia.",
                hint="Use 'discard' em 'transform' se o campo não deve ser mapeado."
            )
            return

        # Campos com transform=discard não precisam de ecs_field válido
        if transform == "discard":
            return

        # Campos com transform=derived não vêm do vendor — ecs_field é o destino
        if transform != "derived":
            # ── ecs_field existe no registry ─────────────────────────────────
            if not self._reg.exists(ecs_field):
                close = self._suggest_close(ecs_field)
                report.add_error(
                    row=row_idx, column="ecs_field",
                    message=f"'{vendor_field}' → campo ECS '{ecs_field}' não existe.",
                    hint=f"Você quis dizer: {close}" if close else
                         "Consulte https://www.elastic.co/guide/en/ecs/current/ecs-field-reference.html"
                )
                return  # sem tipo para validar

            # ── compatibilidade de tipos ──────────────────────────────────────
            if vendor_type:
                try:
                    self._reg.validate_type(ecs_field, vendor_type)
                except ECSTypeError as exc:
                    report.add_error(
                        row=row_idx, column="vendor_type",
                        message=str(exc),
                        hint="Ajuste 'vendor_type' ou use um campo ECS de tipo compatível."
                    )

            # ── nível ECS: avisa campos 'extended' sem justificativa ──────────
            ecs = self._reg.get(ecs_field)
            if ecs.level == "extended":
                notes = row.get("notes", "").strip()
                if not notes:
                    report.add_warning(
                        row=row_idx, column="ecs_field",
                        message=f"'{ecs_field}' é campo ECS 'extended' (não-obrigatório).",
                        hint="Preencha a coluna 'notes' explicando por que este campo é necessário."
                    )

        # ── transform conhecido ───────────────────────────────────────────────
        if transform and transform not in KNOWN_TRANSFORMS:
            report.add_error(
                row=row_idx, column="transform",
                message=f"'{vendor_field}': transform desconhecido: '{transform}'.",
                hint=f"Transforms válidos: {', '.join(sorted(KNOWN_TRANSFORMS))}"
            )

        # ── coluna required deve ser true/false ───────────────────────────────
        if required_str not in {"true", "false", ""}:
            report.add_warning(
                row=row_idx, column="required",
                message=f"'{vendor_field}': valor de 'required' inválido: '{required_str}'.",
                hint="Use 'true' ou 'false'."
            )

    def _suggest_close(self, ecs_field: str) -> Optional[str]:
        """
        Tenta sugerir um campo ECS próximo quando o nome está errado.
        Usa um algoritmo simples baseado em prefixo de field set.
        """
        # Ex: "source.ip_address" → tenta "source.*"
        parts = ecs_field.split(".")
        if len(parts) < 2:
            return None

        prefix = parts[0]
        candidates = [
            f.name for f in self._reg.fields_in_set(prefix)
            if parts[-1] in f.name  # parte final do nome aparece em algum campo
        ]
        if candidates:
            return ", ".join(candidates[:3])  # no máximo 3 sugestões
        return None


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    from generator.ecs.loader import load as load_ecs

    parser = argparse.ArgumentParser(
        description="Valida os CSVs de vendor contra o schema ECS."
    )
    parser.add_argument(
        "path", nargs="?",
        help="Arquivo CSV ou diretório de vendors. Padrão: spec/vendors/"
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]

    # Garante que o ECS está baixado
    load_ecs()

    reg       = ECSRegistry.load()
    validator = VendorValidator(reg)

    target = Path(args.path) if args.path else root / "spec" / "vendors"

    if target.is_file():
        reports = [validator.validate_file(target)]
    else:
        reports = validator.validate_directory(target)

    if not reports:
        print("Nenhum arquivo CSV encontrado.")
        sys.exit(0)

    total_errors = 0
    for report in reports:
        report.print()
        total_errors += len(report.errors)

    print(f"\n{'─'*50}")
    if total_errors:
        print(f"✗  {total_errors} erro(s) encontrado(s). Corrija antes de gerar.")
        sys.exit(1)
    else:
        print(f"✓  Todos os arquivos são válidos.")


if __name__ == "__main__":
    main()
