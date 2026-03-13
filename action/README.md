# PGMind GitHub Action (Docker)

Esta Action executa o `pgmind` dentro de um container Docker para diagnósticos determinísticos em PostgreSQL.

## Runtime da imagem

- A imagem da Action usa o binário de release publicado (`pgmind-linux-x86_64`).
- O Dockerfile embute o tag semântico padrão (`vX.Y.Z`) no container.
- Em runtime, o entrypoint baixa o asset da release correspondente, valida digest SHA-256 (quando disponível) e executa esse binário.
- Para repositórios privados, passe `github_token` (recomendado: `${{ github.token }}`).

## Uso rápido

```yaml
name: pgmind-check

on:
  workflow_dispatch:

jobs:
  check-autovacuum:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run pgmind check
        uses: <owner>/<repo>@v1
        with:
          command: check
          args: "autovacuum --scope selected"
          runtime_profile: production
          db_dsn: ${{ secrets.PGMIND_DB_DSN }}
          github_token: ${{ github.token }}
```

## Exemplo `monitor` com gate de findings

```yaml
name: pgmind-monitor

on:
  workflow_dispatch:
  schedule:
    - cron: "0 * * * *"

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run pgmind monitor
        id: pgmind_monitor
        uses: <owner>/<repo>@v1
        with:
          command: monitor
          args: "--scope selected"
          runtime_profile: production
          db_dsn: ${{ secrets.PGMIND_DB_DSN }}
          github_token: ${{ github.token }}
          fail_on_findings: "true"
      - name: Print artifacts location
        run: |
          echo "summary=${{ steps.pgmind_monitor.outputs.summary_path }}"
          echo "artifacts=${{ steps.pgmind_monitor.outputs.artifacts_path }}"
```

## Local smoke examples (private vs public repository)

Private repository (recommended with token):

```bash
docker run --rm \
  -e INPUT_COMMAND=check \
  -e INPUT_ARGS="autovacuum --scope selected" \
  -e INPUT_RUNTIME_PROFILE=production \
  -e INPUT_DB_DSN="postgresql://postgres:postgres@host.docker.internal:5432/postgres" \
  -e INPUT_GITHUB_TOKEN="<token>" \
  <action-image>
```

Public repository (tokenless, when release asset is publicly accessible):

```bash
docker run --rm \
  -e INPUT_COMMAND=check \
  -e INPUT_ARGS="autovacuum --scope selected" \
  -e INPUT_RUNTIME_PROFILE=production \
  -e INPUT_DB_DSN="postgresql://postgres:postgres@host.docker.internal:5432/postgres" \
  -e INPUT_RELEASE_REPOSITORY="owner/repo" \
  <action-image>
```

## Inputs

| Input | Obrigatório | Default | Descrição |
|---|---|---|---|
| `command` | sim | - | Comando do `pgmind`: `check`, `monitor`, `ask`, `explain-file`. |
| `args` | não | `""` | Argumentos extras para o comando. |
| `runtime_profile` | não | `local` | Exportado como `PGMIND_RUNTIME_PROFILE`. Valores aceitos: `local`, `staging`, `production`. |
| `db_dsn` | não | `""` | DSN PostgreSQL. Recomenda-se sempre `secrets.*`. |
| `llm_enabled` | não | `false` | Exportado como `PGMIND_LLM_ENABLED`. Aceita `true` ou `false`. |
| `fail_on_findings` | não | `false` | Quando `true`, runs de `monitor` com status `warn`, `critical` ou `error` retornam falha da Action. |
| `release_tag` | não | `""` | Tag da release para resolver o binário (quando vazio, usa a tag padrão embutida na imagem). |
| `release_repository` | não | `""` | Repositório `owner/name` para lookup da release (quando vazio, usa o repositório da própria Action). |
| `github_token` | não | `""` | Token opcional para acesso a release privada (recomendado `${{ github.token }}`). |

## Outputs

| Output | Descrição |
|---|---|
| `exit_code` | Código de saída final da execução do `pgmind` (ou gate da Action). |
| `summary_path` | Caminho de `artifacts/monitor/latest.json` quando disponível. |
| `artifacts_path` | Caminho de `artifacts/` quando o diretório existir. |

## Comportamento de segurança

- `db_dsn` é mascarado com `::add-mask::` antes da execução.
- `args` é validado e rejeita:
  - strings de conexão (`scheme://...`);
  - flags sensíveis (`--db-dsn`, `--password`, `--token`, etc.).
- Inputs booleanos (`llm_enabled`, `fail_on_findings`) aceitam apenas `true|false`.
- `runtime_profile` inválido falha a execução com mensagem segura.

## Erros comuns

1. `error: input 'runtime_profile' must be one of: local, staging, production`
   - Ajuste `runtime_profile` para um valor suportado.
2. `error: input 'llm_enabled' must be true or false`
   - Use `llm_enabled: "true"` ou `llm_enabled: "false"`.
3. `error: connection strings are not allowed in 'args'; use the secure 'db_dsn' input`
   - Remova credenciais de `args` e use `db_dsn` com `secrets`.
4. `error: monitor summary was not produced; cannot evaluate findings`
   - Ocorre quando `fail_on_findings=true` mas não existe `artifacts/monitor/latest.json`; revise permissões e execução do `monitor`.
5. `Release asset 'pgmind-linux-x86_64' was not found for tag 'vX.Y.Z'`
   - Publique a release correspondente antes de usar essa versão da Action, ou ajuste a versão para uma tag já publicada.
6. `error: release lookup failed (repository='owner/repo', tag='vX.Y.Z', auth='missing'); tag not found or inaccessible. Provide github_token for private repositories.`
   - Verifique no erro o repositório/tag resolvidos e passe `github_token: ${{ github.token }}` em cenários privados.

## Troubleshooting

1. DSN e credenciais
   - Armazene DSN no secret `PGMIND_DB_DSN`.
   - Nunca passe DSN via `args`.
   - Garanta permissão de rede do runner para o banco.
2. Timeout de conexão/execução
   - Ajuste variáveis de ambiente em etapa anterior (`PGMIND_DB_CONNECT_TIMEOUT`, `PGMIND_DB_STATEMENT_TIMEOUT_MS`) conforme SLA do ambiente.
   - Verifique firewall, DNS e latência entre runner e PostgreSQL.
3. Sem artefatos de monitor
   - Confirme `command: monitor`.
   - Confira logs da etapa para identificar falha anterior ao snapshot.

## Versionamento e compatibilidade

- Esta Action segue semver com tag canônica `vX.Y.Z` e alias major `vX`.
- Recomendação para consumidores:
  - canal estável: `uses: <owner>/<repo>@v1`
  - rollout controlado: `uses: <owner>/<repo>@v1.2.3`
- Mudanças quebrando contrato de inputs/outputs exigem bump major.
- Mudanças aditivas e retrocompatíveis entram em minor/patch, mantendo comportamento padrão.

Para o processo completo de publicação e checklist, consulte `docs/action-release.md`.
