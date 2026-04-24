# Premium Media Hub Bot

Bot Telegram premium para baixar mídias por link, enviar arquivos por URL, tratar arquivos enviados pelo usuário e gerar links compartilháveis.

Ele foi desenhado para não agir sem confirmação: todo link ou arquivo passa por análise e exibe um cartão de ações antes de baixar, reenviar, converter, gerar link ou salvar thumbnail.

## Principais recursos

- Links sociais públicos via `yt-dlp`, com análise antes do download.
- URLs diretas com inspeção de nome, tamanho e tipo.
- Arquivos enviados pelo usuário com central de ações.
- Fotos não viram thumbnail automaticamente.
- Módulo nativo de arquivo para link.
- Thumbnail temporária por tarefa e thumbnail padrão explícita.
- Legendas preservando acentos, emojis e quebras de linha.
- `parse_mode=html` com sanitização segura.
- Upload MTProto com `cryptg` e upload paralelo para arquivos grandes.
- `ffprobe` para resolução, duração e proporção real do vídeo.
- SQLite para usuários, preferências, jobs, links, cache e auditoria.
- Sessão por usuário com TTL, fila, rate limit e limpeza automática.
- Interface preparada para PT-BR, EN e ES.

## Como rodar

```powershell
cd C:\Users\kayky\Downloads\urluploadxbot-clone
python -m pip install -r requirements.txt
python bot.py
```

Configure `.env` com:

```env
API_ID=123456
API_HASH=seu_api_hash
BOT_TOKEN=123456:token
ADMIN_IDS=123456789
PUBLIC_BASE_URL=http://seu-dominio.com/files
```

## VPS pronta para produção

O projeto agora já tem um pacote básico para VPS em `deploy/`:

- `deploy/vps.env.example`: exemplo com caminhos de Linux, mídia efêmera e tuning para produção.
- `deploy/baixa_aquibot.service`: unit file de `systemd`.

### Comportamento efêmero de mídia

Se você quer que o bot faça `baixar -> enviar -> apagar`, use estas opções:

```env
DOWNLOAD_DIR=/tmp/baixa-aqui-bot/downloads
PUBLIC_FILES_DIR=/tmp/baixa-aqui-bot/public_files
PURGE_MEDIA_ON_START=true
LOCAL_LINK_STORAGE_ENABLED=false
LINK_SERVER_ENABLED=false
```

Com isso:

- arquivos baixados para envio são temporários;
- o bot limpa mídias antigas automaticamente;
- ao reiniciar, a mídia temporária restante é removida;
- o fallback de link local fica desativado, então o bot não mantém cópias locais em `public_files`.

Observação:

- histórico, sessão do bot, cache técnico e banco SQLite continuam em `DATA_DIR`;
- mídia de usuário não fica retida para os envios normais;
- links locais de arquivo ficam desativados nesse modo. Para gerar links sem guardar mídia local, use um storage externo.

## Comandos

- `/start` abre a central premium.
- `/ajuda` mostra ajuda curta.
- `/config` abre preferências.
- `/cancelar` cancela tarefas e limpa contexto.
- `/status` ou `/minhastarefas` mostra tarefas.
- `/admin` abre painel administrativo para IDs em `ADMIN_IDS`.

## Fluxos

### Link social

O bot analisa primeiro e mostra tipo, autor, título, duração, itens e qualidade. O download só começa após o usuário tocar em uma ação.

### URL direta

O bot inspeciona `content-type`, `content-length`, nome e extensão. Depois oferece enviar como arquivo, vídeo ou áudio.

### Arquivo enviado

O bot pergunta o que fazer: gerar link, reenviar, renomear, editar legenda, thumbnail ou cancelar.

### Gerar link

O arquivo é copiado para o storage local configurado e recebe um link público. O link pode ser apagado pelo usuário.

## Produção

Instale `ffmpeg`/`ffprobe` para metadados e thumbnails melhores. Em VPS, exponha `PUBLIC_FILES_DIR` por Nginx/Caddy ou use o servidor estático interno (`LINK_SERVER_ENABLED=true`) para testes.

Se quiser mais velocidade em VPS, use uma Bot API local e deixe:

```env
SEND_BACKEND=auto
BOT_API_BASE_URL=http://127.0.0.1:8081
```

### YouTube em VPS

Em alguns servidores, o YouTube pode exigir autenticação e bloquear o `yt-dlp`. O projeto agora aceita:

```env
YTDLP_COOKIES_FILE=/opt/baixa-aquibot/secrets/youtube-cookies.txt
YTDLP_COOKIES_FROM_BROWSER=
YTDLP_EXTRACTOR_ARGS=
YTDLP_USER_AGENT=Mozilla/5.0 (...)
```

O caminho mais confiável para VPS é usar `YTDLP_COOKIES_FILE` com cookies exportados de uma sessão válida do YouTube.

Veja [PRODUCT_SPEC.md](PRODUCT_SPEC.md) para arquitetura, banco, cache, limpeza, administração e escala.
