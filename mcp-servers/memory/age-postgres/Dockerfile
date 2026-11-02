# Postgres da memória com MEMORY_BACKEND=age: Apache AGE (grafo, openCypher) e pgvector (busca semântica) no mesmo
# banco. Os dois têm licença aberta (Apache-2.0 e PostgreSQL). O AGE é carregado em cada sessão (LOAD 'age').
ARG AGE_IMAGE=apache/age:release_PG17_1.7.0
FROM ${AGE_IMAGE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-17-pgvector \
 && rm -rf /var/lib/apt/lists/*
COPY init.sql /docker-entrypoint-initdb.d/10-extensions.sql
