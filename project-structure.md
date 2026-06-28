# network-logs-platform — estrutura do projeto

```
network-logs-platform/
│
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── .gitignore                        # inclui: .env, build/, spec/ecs/fields.csv
├── .env.example
├── docker-compose.yml                # apenas `include:` dos arquivos em docker/compose/
│
# ─────────────────────────────────────────────────────────────
# DOCUMENTAÇÃO
# ─────────────────────────────────────────────────────────────
├── docs/
│   ├── architecture.md
│   ├── ecs.md                        # decisões de mapeamento, campos custom, etc.
│   ├── retention.md                  # política de retenção e conformidade Marco Civil
│   ├── datastreams.md
│   ├── installation.md
│   ├── migration.md
│   ├── snapshots.md
│   ├── vector.md
│   ├── kafka.md
│   ├── opensearch.md
│   ├── goflow2.md
│   ├── images/
│   └── examples/
│
# ─────────────────────────────────────────────────────────────
# DOCKER — infraestrutura e containers
# ─────────────────────────────────────────────────────────────
├── docker/
│   │
│   ├── compose/                      # um arquivo por stack
│   │   ├── opensearch.yml
│   │   ├── vector.yml
│   │   ├── kafka.yml
│   │   ├── goflow2.yml
│   │   ├── dashboards.yml
│   │   └── tools.yml
│   │
│   ├── vector/
│   │   ├── Dockerfile.ingest
│   │   └── Dockerfile.consumer
│   │
│   └── builder/
│       └── Dockerfile                # Python + dependências do gerador
│
# ─────────────────────────────────────────────────────────────
# SCRIPTS — ciclo de vida do projeto
# ─────────────────────────────────────────────────────────────
├── scripts/
│   ├── build.sh                      # docker compose run builder
│   ├── deploy.sh                     # build + up
│   ├── validate.sh                   # só valida spec/, sem gerar nada
│   ├── backup.sh
│   └── restore_snapshot.sh
│
# ─────────────────────────────────────────────────────────────
# SPEC — fonte de verdade editável por humanos
# ─────────────────────────────────────────────────────────────
├── spec/
│   │
│   ├── ecs/
│   │   ├── fields.csv                # GERADO: baixado do elastic/ecs — nunca editar à mão
│   │   └── fields.pin                # versão pinada: "9.5.0" — único arquivo commitado aqui
│   │
│   ├── vendors/                      # mapeamentos vendor → ECS (editáveis)
│   │   ├── fortigate/
│   │   │   ├── connection.csv        # type=traffic + event vpn/user  → retenção 12m
│   │   │   ├── access.csv            # type=utm webfilter/app-ctrl    → retenção 6m
│   │   │   └── security.csv          # type=utm ips/av/dlp + event ops → política interna
│   │   ├── opnsense/
│   │   │   └── ...
│   │   ├── linux/
│   │   │   └── ...
│   │   ├── ruckus/
│   │   │   └── ...
│   │   ├── switch/
│   │   │   └── ...
│   │   └── netflow/
│   │       └── ...
│   │
│   ├── custom_fields/                # campos próprios fora do ECS padrão
│   │   └── uftm.yml                  # ex: uftm.vlan_name, uftm.building — formato ECS YAML
│   │
│   └── examples/                     # logs reais anonimizados para testes e docs
│       ├── fortigate_traffic.log
│       ├── fortigate_utm.log
│       └── ...
│
# ─────────────────────────────────────────────────────────────
# GENERATOR — código Python que lê spec/ e produz build/
# ─────────────────────────────────────────────────────────────
├── generator/
│   ├── build.py                      # ponto de entrada: valida → gera tudo
│   ├── requirements.txt
│   │
│   ├── ecs/
│   │   ├── loader.py                 # baixa fields.csv se não existir, verifica pin
│   │   ├── validator.py              # valida vendor CSVs contra o ECS: tipo, nome, nível
│   │   └── registry.py              # lookup em memória: campo → tipo, nível, descrição
│   │
│   ├── vendors/
│   │   └── parser.py                 # lê spec/vendors/*.csv → estrutura interna
│   │
│   ├── vector/
│   │   └── vrl.py                    # gera arquivos .vrl em build/vector/
│   │
│   ├── opensearch/
│   │   ├── template.py               # gera component/index templates em build/opensearch/
│   │   ├── ism.py                    # gera políticas ISM em build/opensearch/
│   │   └── datastream.py             # gera definições de data streams
│   │
│   └── docs/
│       └── field_reference.py        # gera docs/generated/fields.md
│
# ─────────────────────────────────────────────────────────────
# VECTOR — configuração dos pipelines (source editável)
# ─────────────────────────────────────────────────────────────
├── vector/
│   │
│   ├── ingest/                       # recebe syslog/netflow, publica no Kafka
│   │   ├── vector.yaml
│   │   ├── sources/
│   │   ├── routes/
│   │   └── sinks/
│   │
│   ├── consumer/                     # consome Kafka, transforma, indexa no OpenSearch
│   │   ├── vector.yaml
│   │   │
│   │   ├── vrl/
│   │   │   │
│   │   │   ├── common/               # VRLs compartilhados entre todos os vendors
│   │   │   │   ├── timestamp.vrl     # parse e normalização de @timestamp
│   │   │   │   ├── observer.vrl      # campos observer.* (o firewall em si)
│   │   │   │   ├── event.vrl         # campos event.kind, event.category, event.type
│   │   │   │   ├── related.vrl       # popula related.ip, related.user
│   │   │   │   └── cleanup.vrl       # remove campos raw desnecessários pós-ECS
│   │   │   │
│   │   │   └── vendors/              # VRLs específicos por vendor — GERADOS pelo builder
│   │   │       ├── fortigate/
│   │   │       │   ├── parser.vrl    # parse do key=value do syslog FortiOS
│   │   │       │   ├── router.vrl    # roteia por type+subtype para o VRL correto
│   │   │       │   ├── connection.vrl  # gerado: mapeia traffic + event vpn/user → ECS
│   │   │       │   ├── access.vrl      # gerado: mapeia utm webfilter/app-ctrl → ECS
│   │   │       │   └── security.vrl    # gerado: mapeia utm ips/av/dlp → ECS
│   │   │       ├── opnsense/
│   │   │       ├── linux/
│   │   │       ├── ruckus/
│   │   │       ├── switch/
│   │   │       └── netflow/
│   │   │
│   │   ├── routes/
│   │   └── sinks/
│   │
│   └── tests/                        # inputs JSON para `vector test`
│       ├── fortigate/
│       │   ├── traffic_forward.json
│       │   ├── utm_webfilter.json
│       │   └── event_vpn.json
│       ├── opnsense/
│       └── ...
│
# ─────────────────────────────────────────────────────────────
# OPENSEARCH — configuração e definições (source editável)
# ─────────────────────────────────────────────────────────────
├── opensearch/
│   │
│   ├── config/
│   │   ├── opensearch.yml
│   │   ├── internal_users.yml
│   │   └── roles.yml
│   │
│   ├── ism/                          # templates ISM por classe legal/operacional
│   │   ├── connection_12m.json       # traffic + event vpn/user: hot→warm→delete 12m
│   │   ├── access_6m.json            # utm webfilter/app-ctrl: hot→warm→delete 6m
│   │   ├── security_90d.json         # utm ips/av/dlp: política interna
│   │   └── ops_30d.json              # event operacional: política interna
│   │
│   ├── snapshots/
│   │   ├── repository.json
│   │   ├── policies.json
│   │   └── restore_examples.md
│   │
│   └── dashboards/
│
# ─────────────────────────────────────────────────────────────
# KAFKA
# ─────────────────────────────────────────────────────────────
├── kafka/
│   ├── server.properties
│   ├── topics/
│   └── consumers/
│
# ─────────────────────────────────────────────────────────────
# GOFLOW2
# ─────────────────────────────────────────────────────────────
├── goflow2/
│   ├── goflow2.yml
│   └── templates/
│
# ─────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────
├── tests/
│   ├── vector/                       # testes de pipeline VRL
│   ├── opensearch/                   # testes de template e ISM
│   └── generator/                    # testes unitários do builder Python
│
# ─────────────────────────────────────────────────────────────
# BUILD — artefatos gerados, nunca editados à mão
#         inteiro no .gitignore, exceto o .gitkeep
# ─────────────────────────────────────────────────────────────
└── build/
    ├── .gitkeep
    ├── vector/
    │   └── vendors/
    │       └── fortigate/
    │           ├── connection.vrl
    │           ├── access.vrl
    │           └── security.vrl
    ├── opensearch/
    │   ├── templates/
    │   │   ├── component/
    │   │   └── index/
    │   ├── ism/
    │   └── datastreams/
    └── docs/
        └── field_reference.md        # referência de campos gerada automaticamente
```

---

## Diferenças em relação à proposta original

| O que mudou | Por quê |
|---|---|
| `spec/ecs/` só tem `fields.csv` + `fields.pin` | O CSV é baixado do upstream, não escrito à mão. O `fields.pin` é o único arquivo que se commita aqui |
| `spec/vendors/` separado de `spec/ecs/` | Naturezas diferentes: referência vs. input do gerador |
| `spec/custom_fields/uftm.yml` | Campos próprios da UFTM fora do ECS padrão, em formato YAML compatível com o gerador ECS |
| `spec/examples/` | Logs reais anonimizados: servem para testes e para documentar o comportamento esperado do parser |
| `opensearch/mappings/` removida | Mappings são *gerados* pelo builder a partir do spec — não existem como source editável |
| `opensearch/templates/` movida para `build/` | Idem: são artefatos gerados |
| `opensearch/ism/` renomeada por classe legal | Nomes alinhados com a obrigação: `connection_12m`, `access_6m`, etc. |
| `vector/consumer/vrl/vendors/` só tem VRLs gerados | `generated/` sumiu — build vai para `build/`, não fica dentro do source |
| `vector/consumer/vrl/vendors/fortigate/router.vrl` | Arquivo novo: o Vector precisa de um roteador que lê `type`+`subtype` e chama o VRL certo |
| `docker/scripts/` removida | Consolidado em `scripts/` na raiz com taxonomia clara |
| `generator/ecs/parser.py` → `registry.py` + `validator.py` | Separação de responsabilidade: registry faz lookup, validator aplica as regras |
| `generator/vendors/parser.py` adicionado | Lê os CSVs de vendor e produz estrutura interna uniforme |
| `tests/generator/` adicionado | Testes unitários do builder Python — sem eles não há como refatorar o gerador com confiança |

---

## Fluxo de trabalho

```
# 1. Editar o mapeamento de um campo no FortiGate
vim spec/vendors/fortigate/connection.csv

# 2. Validar (sem gerar nada)
./scripts/validate.sh

# 3. Gerar todos os artefatos
docker compose run builder
# → build/vector/vendors/fortigate/connection.vrl
# → build/opensearch/templates/...
# → build/docs/field_reference.md

# 4. Subir o ambiente
docker compose up
```

---

## Schema do CSV de vendor

Cada linha é um campo de um vendor mapeado para ECS.

```
vendor_field, vendor_type, fgt_type, fgt_subtype, ecs_field, transform, required, notes
```

| Coluna | Descrição | Exemplo |
|---|---|---|
| `vendor_field` | Nome exato do campo no log do vendor | `srcip` |
| `vendor_type` | Tipo no vendor (para validação e cast) | `ip` |
| `fgt_type` | Valor do campo `type` do FortiOS | `traffic` |
| `fgt_subtype` | Valor do campo `subtype`, ou `*` para todos | `*` |
| `ecs_field` | Campo ECS de destino — validado contra `spec/ecs/fields.csv` | `source.ip` |
| `transform` | Transformação a aplicar no VRL gerado | `ip_validate`, `to_int`, `mul:1000000000`, `copy` |
| `required` | Se ausente no log, emitir warning? | `true` |
| `notes` | Comentário para o gerador de docs | `"FGT em segundos, ECS em nanosegundos"` |
