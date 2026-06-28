"""
generator/ecs/registry.py

Carrega o spec/ecs/fields.csv em memória e expõe uma API de consulta.

Uso típico (pelo validator e pelo gerador):

    from generator.ecs.registry import ECSRegistry

    reg = ECSRegistry.load()

    field = reg.get("source.ip")
    # ECSField(name='source.ip', field_set='source', type='ip', level='core', description='...')

    reg.exists("source.ip")     # True
    reg.exists("source.xpto")   # False

    reg.validate_type("source.bytes", "integer")
    # Levanta ECSTypeError se o tipo esperado for incompatível com o tipo ECS
"""

import csv
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Optional

# ── Modelo ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ECSField:
    name:        str   # ex: "source.ip"
    field_set:   str   # ex: "source"
    type:        str   # ex: "ip", "keyword", "long", "date", "boolean"
    level:       str   # "core" | "extended" | "custom"
    description: str
    example:     str


# Mapa de compatibilidade de tipos: tipo do vendor → tipos ECS aceitos.
# Usado pelo validator para detectar mismatches óbvios (ex: string → long).
COMPATIBLE_TYPES: dict[str, set[str]] = {
    "ip":       {"ip", "keyword", "wildcard"},
    "integer":  {"long", "integer", "short", "byte", "float", "double"},
    "float":    {"float", "double", "long"},
    "string":   {"keyword", "text", "wildcard", "match_only_text"},
    "boolean":  {"boolean", "keyword"},
    "date":     {"date", "keyword"},
    "mac":      {"keyword"},
}

# ── Erros específicos ─────────────────────────────────────────────────────────

class ECSFieldNotFoundError(Exception):
    """Campo ECS não existe no registry."""

class ECSTypeError(Exception):
    """Tipo do vendor incompatível com o tipo ECS do campo."""

# ── Registry ──────────────────────────────────────────────────────────────────

class ECSRegistry:
    """
    Registry imutável dos campos ECS carregados de spec/ecs/fields.csv.

    Use ECSRegistry.load() para obter uma instância — o arquivo é lido
    apenas uma vez e cacheado.
    """

    # Colunas esperadas no fields.csv do ECS (nomes reais do arquivo gerado)
    _COL_FIELD_SET  = "Field Set"
    _COL_FIELD      = "Field"
    _COL_TYPE       = "Type"
    _COL_LEVEL      = "Level"
    _COL_DESCRIPTION = "Description"
    _COL_EXAMPLE    = "Example"

    def __init__(self, fields: dict[str, ECSField]) -> None:
        self._fields = fields

    # ── Carregamento ──────────────────────────────────────────────────────────

    @classmethod
    def load(cls, csv_path: Optional[Path] = None) -> "ECSRegistry":
        """
        Carrega o registry a partir do fields.csv.

        Parâmetros
        ----------
        csv_path : Path opcional. Se None, usa spec/ecs/fields.csv relativo à raiz do projeto.
        """
        if csv_path is None:
            root = Path(__file__).resolve().parents[2]
            csv_path = root / "spec" / "ecs" / "fields.csv"

        if not csv_path.exists():
            raise FileNotFoundError(
                f"spec/ecs/fields.csv não encontrado em {csv_path}.\n"
                "Execute: python -m generator.ecs.loader"
            )

        fields: dict[str, ECSField] = {}

        with csv_path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            cls._check_columns(reader.fieldnames or [], csv_path)

            for row in reader:
                name = row[cls._COL_FIELD].strip()
                if not name:
                    continue
                fields[name] = ECSField(
                    name        = name,
                    field_set   = row[cls._COL_FIELD_SET].strip(),
                    type        = row[cls._COL_TYPE].strip(),
                    level       = row[cls._COL_LEVEL].strip(),
                    description = row[cls._COL_DESCRIPTION].strip(),
                    example     = row.get(cls._COL_EXAMPLE, "").strip(),
                )

        return cls(fields)

    @classmethod
    def _check_columns(cls, fieldnames: list[str], csv_path: Path) -> None:
        """Verifica que as colunas necessárias existem no CSV."""
        required = {
            cls._COL_FIELD_SET, cls._COL_FIELD,
            cls._COL_TYPE, cls._COL_LEVEL, cls._COL_DESCRIPTION,
        }
        missing = required - set(fieldnames)
        if missing:
            raise ValueError(
                f"fields.csv ({csv_path}) não tem as colunas esperadas: {missing}\n"
                f"Colunas encontradas: {fieldnames}\n"
                "A estrutura do ECS CSV pode ter mudado. Verifique a versão em fields.pin."
            )

    # ── API de consulta ───────────────────────────────────────────────────────

    def get(self, field_name: str) -> ECSField:
        """
        Retorna o ECSField para o campo dado.
        Levanta ECSFieldNotFoundError se não existir.
        """
        field = self._fields.get(field_name)
        if field is None:
            raise ECSFieldNotFoundError(
                f"Campo ECS não encontrado: '{field_name}'\n"
                f"Verifique o nome em https://www.elastic.co/guide/en/ecs/current/ecs-field-reference.html"
            )
        return field

    def exists(self, field_name: str) -> bool:
        """Retorna True se o campo existe no ECS."""
        return field_name in self._fields

    def validate_type(self, ecs_field_name: str, vendor_type: str) -> None:
        """
        Verifica se o tipo do vendor é compatível com o tipo ECS do campo.

        Parâmetros
        ----------
        ecs_field_name : Nome do campo ECS (ex: "source.ip")
        vendor_type    : Tipo declarado no CSV do vendor (ex: "ip", "string", "integer")

        Levanta
        -------
        ECSFieldNotFoundError : Se o campo não existir no ECS.
        ECSTypeError          : Se o tipo do vendor for incompatível com o ECS.
        """
        ecs_field = self.get(ecs_field_name)
        compatible = COMPATIBLE_TYPES.get(vendor_type.lower())

        if compatible is None:
            # Tipo desconhecido no vendor — avisa mas não bloqueia
            return

        if ecs_field.type not in compatible:
            raise ECSTypeError(
                f"Tipo incompatível para '{ecs_field_name}':\n"
                f"  vendor declara tipo '{vendor_type}' → compatível com ECS types {compatible}\n"
                f"  mas o campo ECS é do tipo '{ecs_field.type}'\n"
                f"Verifique a coluna 'vendor_type' no CSV do vendor."
            )

    # ── Utilitários ───────────────────────────────────────────────────────────

    @cached_property
    def field_sets(self) -> set[str]:
        """Conjunto de todos os field sets presentes no ECS."""
        return {f.field_set for f in self._fields.values()}

    @cached_property
    def core_fields(self) -> list[ECSField]:
        """Lista de campos de nível 'core' (os mais importantes)."""
        return [f for f in self._fields.values() if f.level == "core"]

    def fields_in_set(self, field_set: str) -> list[ECSField]:
        """Lista todos os campos de um field set (ex: 'source', 'destination', 'network')."""
        return [f for f in self._fields.values() if f.field_set == field_set]

    def __len__(self) -> int:
        return len(self._fields)

    def __repr__(self) -> str:
        return f"ECSRegistry({len(self)} campos)"
