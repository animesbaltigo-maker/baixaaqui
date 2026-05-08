# Auditoria tecnica do BaixaAqui Bot

Data: 2026-05-08
Escopo: bot Telegram async com Telethon, Bot API, yt-dlp, aria2c, gallery-dl, FFmpeg, conversoes e storage local.

## A. Resumo executivo brutal

O projeto tem uma base util: modulos separados para download, social, conversao, progresso, banco, seguranca, limpeza e upload paralelo; usa semaforos; tem cache de file_id; usa WAL no SQLite; tem testes basicos; e ja tenta cobrir Google Drive, yt-dlp, gallery-dl e Bot API local.

O risco real esta em producao sob carga. O `bot.py` ainda concentra orquestracao, handlers, UI, estado global, filas e servidor HTTP. Isso dificulta teste, evolucao e escala horizontal. Estado critico fica em memoria (`pending_targets`, `active_tasks`, `download_dedupe`), entao restart perde contexto e multi-processo fica inconsistente.

O maior problema de performance confirmado era o upload paralelo: o `file_lock` serializava a leitura de partes, reduzindo o ganho real. O segundo era o `aria2c --quiet` combinado com parse de progresso, que impedia progresso util no download direto. Ambos foram corrigidos.

O maior problema de seguranca confirmado e operacional, nao so codigo: `.env`, `data/premium.sqlite3` e `data/urlupload_bot.session` existem dentro da pasta do projeto. Mesmo com `.gitignore`, isso e risco critico em zip, backup, print, deploy e compartilhamento. Rotacione token/sessao antes de qualquer producao.

O alvo "2 GB em 30 segundos" exige pelo menos 533 Mbps reais so de transferencia, sem overhead. E possivel para download de CDN boa em VPS com rede e NVMe bons. Upload para Telegram e menos previsivel: depende de DC, rota, flood limits, backend usado e horario.

## B. Problemas por severidade

### Critico

- `.env` existe no projeto com possiveis segredos. Impacto: comprometimento total do bot/contas. Acao: rotacionar token/API/sessao, manter fora de zip/deploy.
- `data/urlupload_bot.session` existe. Impacto: sessao Telethon autenticada pode vazar. Acao: recriar sessao, remover de artefatos, permissao 600/700 em Linux.
- `bot.py` usa estado global em memoria para jobs e callbacks. Impacto: perda de estado em crash, impossibilidade de escala horizontal correta.
- SSRF ainda nao esta completo contra redirects/DNS rebinding. `validate_public_url` bloqueia IP literal privado, mas chamadas com `allow_redirects=True` podem seguir para destino interno antes de revalidar.

### Alto

- `bot.py` tem 1962 linhas e mistura handlers, negocio, UI, fila e infra.
- `download_dedupe` usa locks globais e remove o lock no `finally`; em cenarios de espera concorrente pode liberar a chave enquanto outro job ainda usa a lock antiga.
- Semaforos sao aninhados: `job_slots` envolve `download_slots`/`upload_slots`. Sob alta carga, isso pode prender slots de job enquanto aguardam etapa interna.
- Bot API e downloads diretos usam `ClientTimeout(total=None)`. Isso evita matar upload grande legitimo, mas permite job zumbi se houver fluxo lento intermitente.
- `security.py` e `downloader.py` seguem redirects automaticamente.
- `gallery-dl`, `yt-dlp` e FFmpeg ainda rodam sem limite de CPU/memoria por processo.
- Link server/local file server precisa de rate limit por IP, assinatura/HMAC e hardening contra enumeracao/hotlink.

### Medio

- SQLite abre conexao por operacao; aceitavel pequeno, ruim sob alta concorrencia.
- `_known_users` em `database.py` cresce sem TTL.
- `cleanup.py` remove por idade sem lease/lock de job; se clock/TTL estiver ruim, pode competir com job longo.
- Progresso ainda usa media desde o inicio; UX premium precisa janela deslizante para velocidade atual e ETA mais confiavel.
- `media_probe.py` usa subprocess em thread com timeout, mas logs de ferramenta/tempo ainda sao pobres.
- `PDF -> CBZ` usa `Matrix(2, 2)`, bom para qualidade, caro para CPU/RAM.
- Default `PARALLEL_UPLOAD_THRESHOLD_MB=5` dispara upload paralelo em arquivos pequenos demais.

### Baixo

- `human_size` usa base 1024 com labels KB/MB/GB, tecnicamente deveria ser KiB/MiB/GiB ou mudar para base 1000.
- `_legacy_humanize_provider_error` duplica logica de `humanize_provider_error`.
- `RateLimiter` era leak lento por usuarios antigos; foi mitigado.
- `parallel_upload_workers=12` como default e agressivo; agora o codigo auto-reduz por tamanho, mas o default ainda merece baixar para 8 ou 6.

## C. Auditoria arquivo por arquivo

### bot.py

Responsabilidades demais: boot, singletons, handlers, botoes, cards, status, filas, jobs, uploads, link server e limpeza. Separar em `handlers/`, `jobs/`, `ui/`, `state/` e `app.py`.

Pontos de escala: `pending_targets`, `active_tasks` e `download_dedupe` sao memoria local. Em multi-VPS ou multi-processo, cada processo enxerga mundo diferente.

Pontos alterados: agora escolhe workers de upload por tamanho e loga fallback do upload paralelo em vez de `except Exception: pass`.

### urluploader/downloader.py

Antes: `aria2c --quiet` com `summary-interval=0`, parseando stdout. Isso nao entrega progresso real. Agora: sem `--quiet`, `summary-interval=1`, retry, split mais conservador, `.part` antes do arquivo final e chunk aiohttp de 8 MB.

Ainda falta: retry com backoff no fallback aiohttp, redirect seguro manual, limite por velocidade minima, protecao DNS rebinding, fila por tamanho/origem.

### urluploader/social.py

yt-dlp esta bem equipado: `--newline`, retries, fragments, socket timeout, max filesize, cookies por plataforma. Ajuste aplicado: removido `--no-part` e aria2 embutido saiu de quiet/summary 0 para retries e progresso.

Ainda falta: limites por processo, timeout global por job social, perfis por dominio, fallback seletivo entre native/aria2c, benchmark por plataforma.

### urluploader/parallel_upload.py

Antes: todos os workers compartilhavam um handle e um `file_lock`; leitura era serializada. Agora: cada worker abre seu proprio handle, mantendo concorrencia de envio e evitando seek concorrente no mesmo objeto. Tambem foi adicionado `upload_workers_for_size`.

Ainda falta: capturar `FloodWaitError` com backoff, metricas por parte, limite adaptativo por DC, benchmark workers 2/4/6/8.

### urluploader/progress.py

Bom: throttle por intervalo e `percent_step`, tratamento de FloodWait/MessageNotModified. Ajuste aplicado: evita acumular tasks de edicao pendentes quando callbacks chegam rapido demais.

Ainda falta: `SpeedMeter` com janela deslizante, ETA suavizado, progresso de fila, progresso de FFmpeg e padrao visual por etapa.

### urluploader/conversion.py

Antes: FFmpeg bloqueava uma thread do pool com `subprocess.run`; CBZ->PDF carregava todas as imagens em memoria. Agora: FFmpeg usa subprocess async com timeout, e CBZ->PDF cria paginas com PyMuPDF uma a uma. Tambem foi adicionada validacao basica contra zip bomb/path traversal.

Ainda falta: progresso real via `-progress pipe:1`, timeout configuravel por conversao, limites por tipo, matrix menor em PDF->CBZ para modo rapido.

### urluploader/security.py

Bom: bloqueia esquemas nao HTTP(S), localhost, `.local` e IP literal privado. Insuficiente para SSRF moderno: nao valida cada redirect e nao bloqueia DNS que resolve para IP privado no momento da conexao.

Proxima correcao recomendada: `SSRFSafeConnector` ou redirects manuais sem `allow_redirects=True`, revalidando host e IP resolvido a cada salto.

### urluploader/http_client.py

Bom: sessao compartilhada, connector com limites e keepalive. Risco: connector nao e SSRF-safe, `limit_per_host=80` pode ser agressivo para alguns dominios.

### urluploader/drive.py

Bom: suporte a confirm token, streaming e limite por tamanho. Faltam: backoff robusto, tratamento completo de quota/intersticial, OAuth opcional e redirect seguro.

### urluploader/bot_api.py

Boa separacao para Bot API. Risco: `ClientTimeout(total=None)` pode manter job pendurado. Producao deve ter timeout total alto mas finito, e abort por baixa velocidade.

### urluploader/database.py

Bom: tabelas adequadas, WAL, indices, cache de file_id. Riscos: conexao por operacao, SQLite sync em bot async, `_known_users` sem TTL. Para milhares simultaneos, migrar jobs/cache para PostgreSQL e progresso/rate-limit para Redis.

### urluploader/runtime.py

RateLimiter simples e eficiente para pouco volume. Ajuste aplicado: remove entradas expiradas vazias para reduzir leak lento.

### urluploader/cleanup.py

Simples e util, mas falta lease por job e checagem de espaco livre antes de aceitar job. Em producao, recusar download se disco livre < margem configurada.

### urluploader/link_storage.py

Gera link local e hash. Falta assinatura/HMAC, rate limit do servidor de arquivos, TTL reforcado e logs por acesso.

### urluploader/names.py

Tem sanitizacao e limite de comprimento. Verificar mais tarde: nomes reservados Windows (`CON`, `NUL`, `PRN`), extensao enganosa e normalizacao Unicode.

### urluploader/media_probe.py

Tem probe e thumbnail. Precisa logs com duracao, timeout por ferramenta e evitar subprocess em threadpool para operacoes longas.

### tests/

Tem bons testes de nomes, cookies, perfis e hardening basico. Falta cobertura dos fluxos mais perigosos: progresso aria2c, upload paralelo, SSRF redirect, DNS privado, cancelamento, zip bomb, arquivo enorme, flood wait, stress test.

## D. Plano de refatoracao em fases

### Fase 1: urgencia

- Rotacionar credenciais e sessao.
- Remover segredos/sessoes/bancos/logs de qualquer zip/deploy.
- Aplicar redirect-safe SSRF.
- Adicionar timeout total alto mas finito e abort por velocidade minima.
- Reduzir defaults agressivos: jobs 8, downloads 4, uploads 2, jobs por usuario 1, parallel workers 6-8.
- Adicionar logs para todos os fallbacks silenciosos.

### Fase 2: performance

- Benchmark aria2c split 4/8/16 por dominio.
- Auto-ajuste por tamanho/origem.
- Local Bot API com envio por caminho local.
- Cache por hash + file_id.
- Evitar conversao quando container/codec ja servem.
- FFmpeg copy primeiro, reencode so quando necessario.

### Fase 3: arquitetura escalavel

- Separar frontend Telegram de workers.
- Redis Streams/arq para fila e progresso.
- PostgreSQL para jobs/cache/usuarios.
- Workers separados para download, conversao e upload.
- Storage temporario em NVMe local; cache compartilhado em S3/MinIO se houver multiplas VPS.

### Fase 4: UX premium

- Estados fixos: analisando, fila, baixando, juntando, convertendo, enviando, finalizando.
- Barra + porcentagem + baixado/enviado + velocidade atual + media + ETA.
- Botao cancelar sempre visivel.
- Progresso FFmpeg via `-progress`.
- Posicao na fila e estimativa.

### Fase 5: megaestrutura

- Bot frontend stateless.
- Redis para fila, locks, rate limit e progresso.
- PostgreSQL para persistencia.
- Prometheus/Grafana/Loki/Sentry.
- Workers escalaveis por tipo.
- Admin panel com jobs ativos, fila, erro, disco, throughput e cancelamento.

## E. Sugestoes concretas

### Redirect seguro

```python
async def safe_request(session, method, url, *, max_redirects=5, **kwargs):
    current = url
    for _ in range(max_redirects + 1):
        validate_public_url(current)
        async with session.request(method, current, allow_redirects=False, **kwargs) as response:
            if response.status not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("Location")
            if not location:
                return response
            current = str(response.url.join(URL(location)))
    raise DownloadError("Redirecionamentos demais.")
```

### Velocidade por janela

```python
class SpeedMeter:
    def __init__(self, window=8):
        self.samples = deque(maxlen=window)

    def update(self, current):
        now = time.monotonic()
        self.samples.append((now, current))
        if len(self.samples) < 2:
            return 0.0
        t0, b0 = self.samples[0]
        t1, b1 = self.samples[-1]
        return (b1 - b0) / max(t1 - t0, 0.001)
```

### Progresso FFmpeg

```python
cmd = [ffmpeg, "-i", input_path, "...", "-progress", "pipe:1", "-nostats", output_path]
```

Ler `out_time_ms` e converter para porcentagem usando duracao do `ffprobe`.

## F. Checklist de producao

- [ ] Rotacionar BOT_TOKEN, API_ID/API_HASH se expostos e sessao Telethon.
- [ ] `.env`, `data/`, `logs/`, `downloads/`, `cookies/` fora de zip/deploy publico.
- [ ] `chmod 600 .env` e `chmod 700 data logs cookies downloads` em Linux.
- [ ] `ALLOW_PRIVATE_DOWNLOADS=false`.
- [ ] Local Bot API configurado se o objetivo for velocidade alta.
- [ ] aria2c, ffmpeg, ffprobe, yt-dlp, gallery-dl instalados e versionados.
- [ ] Semaforos conservadores para VPS comum.
- [ ] Limite por usuario, grupo, dominio e tamanho.
- [ ] Cleanup no boot e periodico.
- [ ] Alerta de disco > 80%.
- [ ] Logs estruturados.
- [ ] Metricas Prometheus.
- [ ] Testes de 50 MB, 500 MB e 1.9 GB.
- [ ] Testes de cancelamento, flood wait, SSRF e zip bomb.

## G. Plano de benchmark

Coletar por job: `job_id`, `domain`, `source_type`, `file_size`, `queue_wait_ms`, `inspect_ms`, `download_ms`, `download_avg_mbps`, `download_peak_mbps`, `conversion_ms`, `upload_ms`, `upload_avg_mbps`, `backend_used`, `aria2_used`, `workers`, `error_type`.

Download: testar 100 MB, 500 MB, 1 GB, 2 GB com aiohttp, aria2c split 4/8/16 e yt-dlp native/aria2c.

Upload: comparar Telethon normal, Telethon paralelo 2/4/6/8, Bot API publica e Local Bot API.

Conversao: medir FFmpeg copy, reencode, PDF->CBZ, CBZ->PDF, EPUB->CBZ. Registrar CPU, RAM pico, disco, tempo e tamanho de saida.

Melhorou se p50/p90/p99 caem, taxa de erro cai, flood wait/hora cai, MB/s sobem e RAM/disco ficam previsiveis.

## H. Melhorias aplicadas nesta auditoria

- `downloader.py`: aria2c sem quiet, progresso a cada 1s, retries, split 8, `.part`, chunk fallback 8 MB e fallback logado.
- `parallel_upload.py`: removido lock global de leitura; um handle por worker; workers automaticos por tamanho.
- `bot.py`: usa workers automaticos e loga fallback do upload paralelo.
- `progress.py`: cancela task de edicao pendente para evitar acumulacao.
- `conversion.py`: FFmpeg async com timeout; CBZ->PDF pagina a pagina; validacao basica de zip bomb/path traversal.
- `social.py`: yt-dlp/gallery-dl voltam a usar arquivos `.part`; aria2c do yt-dlp sem quiet e com retries.
- `runtime.py`: rate limiter limpa chaves expiradas vazias.

Validacao feita:

- `python -m unittest discover -s tests` passou: 33 testes.
- `python -m py_compile bot.py urluploader/*.py` passou com lista explicita de arquivos.
