# Network Logs Platform
"Turning heterogeneous network logs into a unified observability platform".

### Goflow2 • Vector • Kafka • OpenSearch • ECS • Data Streams

![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![OpenSearch](https://img.shields.io/badge/OpenSearch-2.x-005EB8)
![Vector](https://img.shields.io/badge/Vector-0.48-green)
![Kafka](https://img.shields.io/badge/Kafka-4.x-black)

---

A modular observability platform for collecting, normalizing, processing and storing Syslog and NetFlow/IPFIX logs using GoFlow2, Vector, Kafka and OpenSearch.

Designed around the Elastic Common Schema (ECS), OpenSearch Data Streams, Index State Management (ISM) and modular Vector pipelines, it provides a scalable foundation for network observability, security monitoring and long-term log retention.

---
## Project Status

🚧 Under active development.

The project is currently focused on building the core ingestion pipeline and
ECS normalization before releasing the first stable version.

---

## Features

- Syslog collection
- NetFlow v9 / IPFIX collection
- Elastic Common Schema (ECS) normalization
- OpenSearch Data Streams
- Index State Management (ISM)
- Automatic snapshots
- Multi-vendor parsers
- Docker Compose deployment 

## Project Goals

- Normalize heterogeneous logs into a unified ECS model.
- Support multiple network vendors through modular parsers.
- Provide scalable long-term log retention using OpenSearch Data Streams.
- Simplify investigations with standardized field names.
- Support legal compliance with configurable retention policies.
- Minimize storage usage through lifecycle management.

## Why?

Most network environments collect logs from multiple vendors using different
field names, formats and semantics.

This project normalizes heterogeneous Syslog and NetFlow/IPFIX events into a
single ECS-compatible data model, making searches, dashboards, lifecycle
policies and forensic investigations consistent across all supported devices.

## Supported Devices

- Fortinet FortiGate Firewalls
- OPNsense Firewalls
- Linux Servers
- Ruckus Wireless Access Points and Controllers
- Generic Network Switches
- Generic Syslog Devices
- NetFlow v9 / IPFIX Exporters

## Architecture

```text
                +-----------------+
                | Network Devices |
                +-----------------+
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
+------------------+            +-------------------+
|  Vector Ingest   |            |      GoFlow2      |
|     (Syslog)     |            |  (NetFlow/IPFIX)  |
+------------------+            +-------------------+
                 │                  │
                 └──────────┬───────┘
                            ▼
                     +---------------+
                     |     Kafka     |
                     +---------------+
                            │
                            ▼
                  +-------------------+
                  |  Vector Consumer  |
                  | ECS Normalization |
                  +-------------------+
                            │
                            ▼
                   +------------------+
                   |   OpenSearch     |
                   |  Data Streams    |
                   +------------------+
                            │
                            ▼
                    +----------------+
                    |   Dashboards   |
                    +----------------+
```

## Repository Structure

```text
docs/
docker/
vector/
opensearch/
tests/
scripts/
examples/
```

## Documentation

Documentation is available in the `docs/` directory.

## License

Licensed under the Apache License 2.0.

---

## Project Origin

This project was originally developed for the **Universidade Federal do Triângulo Mineiro (UFTM)** to support compliance with the **Brazilian Marco Civil da Internet (Law No. 12,965/2014)** requirements for network log retention.

---

Copyright © 2026  
Guilherme de Lima Gontijo
