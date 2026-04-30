# Produto: Premium Media Hub Bot

## Arquitetura

O bot usa Telethon com token de bot para manter upload MTProto rapido e suporte melhor a arquivos grandes. A arquitetura foi separada em camadas:

- `bot.py`: composição da aplicação, handlers, callbacks e ciclo de vida.
- `urluploader/config.py`: configuração por ambiente.
- `urluploader/premium_i18n.py`: textos e botões em PT, EN e ES.
- `urluploader/html_text.py`: sanitização para `parse_mode=html`.
- `urluploader/runtime.py`: sessão por usuário com TTL e rate limit.
- `urluploader/database.py`: SQLite relacional para usuários, jobs, cache, links e auditoria.
- `urluploader/downloader.py`: provider de URL direta com inspeção `HEAD`/range e download.
- `urluploader/social.py`: provider de redes sociais via `yt-dlp`, com análise antes do download.
- `urluploader/media_probe.py`: `ffprobe`/`ffmpeg` para duração, resolução, aspecto e thumbnail.
- `urluploader/link_storage.py`: módulo arquivo-para-link com storage local desacoplado.
- `urluploader/parallel_upload.py`: upload paralelo para arquivos grandes.
- `urluploader/cleanup.py`: limpeza automática de temporários e cache operacional.

## Fluxos

### Link social

1. Usuário envia link.
2. Bot analisa metadados sem baixar.
3. Bot mostra cartão com tipo, autor, título, duração, itens e qualidade.
4. Usuário escolhe baixar vídeo, extrair áudio, baixar imagens, baixar tudo, editar legenda, renomear ou cancelar.
5. Bot executa, edita uma mensagem de status e limpa temporários.

### URL direta

1. Usuário envia URL.
2. Bot inspeciona nome, tamanho, tipo e extensão.
3. Bot mostra confirmação com botões de envio como arquivo, vídeo ou áudio.
4. Download só começa após confirmação.

### Arquivo enviado

1. Usuário envia foto, vídeo, áudio ou documento.
2. Bot pergunta o que fazer.
3. Opções: gerar link, reenviar, renomear, editar legenda, definir thumbnail ou cancelar.
4. Foto nunca vira thumbnail automaticamente.

### Arquivo para link

1. Usuário escolhe `Gerar link`.
2. Bot baixa o arquivo para temporário isolado por job.
3. Storage adapter valida e publica no diretório configurado.
4. Bot retorna link público com botão de abrir e apagar.

## Banco

Tabelas:

- `users`: idioma, plano e bloqueio.
- `preferences`: thumbnail padrão e preferências.
- `jobs`: histórico operacional de tarefas.
- `links`: links gerados, hash, tamanho, expiração e caminho interno.
- `cache`: metadados de links com TTL.
- `audit`: ações administrativas.

## Cache e limpeza

- Metadados sociais são cacheados por `METADATA_CACHE_TTL_SECONDS`.
- Sessões expiram por `SESSION_TTL_SECONDS`.
- Diretórios temporários são limpos por `TEMP_TTL_HOURS`.
- Conteúdo bruto não é mantido permanentemente, exceto links gerados e thumbs salvas explicitamente.

## Administração

Configure `ADMIN_IDS` no `.env`.

Comandos:

- `/admin`: visão geral do sistema.
- `/status` ou `/minhastarefas`: tarefas do usuário.
- `/config`: idioma e preferências.
- `/cancelar`: cancela tarefas e limpa contexto.

## Escala

- Uploads e downloads são limitados por semáforos globais.
- Rate limit por usuário reduz flood.
- Jobs usam isolamento por diretório temporário.
- Para produção, use VPS com boa rota para Telegram, `cryptg`, `ffmpeg`/`ffprobe`, e considere Bot API local se quiser publicar arquivos via servidor local.
