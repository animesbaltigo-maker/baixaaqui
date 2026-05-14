# Baixa Aqui

Bot Telegram premium para baixar midias por link, reenviar arquivos, converter documentos e gerar links temporarios. Ele usa Telethon, yt-dlp, gallery-dl, aiohttp, SQLite e upload otimizado para VPS.

## Recursos

- YouTube, YouTube Music, TikTok, Instagram, X/Twitter, Facebook, Pinterest, Reddit, SoundCloud, Twitch, Vimeo e links diretos.
- Crunchyroll com cookies da conta do dono do bot.
- Qualidades reais do YouTube extraidas do JSON do yt-dlp.
- Cookies fixos por plataforma para VPS.
- Fallback yt-dlp -> gallery-dl em redes sociais.
- Download direto com aria2c quando disponivel.
- Upload por Telethon, Bot API e Local Bot API quando configurado.
- Modo grupo silencioso: baixa e envia sem progresso ou erro visivel.
- Links temporarios por storage local e fallback de hosts de imagem.
- Diagnostico de VPS via `/health` ou `python scripts/diagnose.py`.
- Logs rotativos e opcao `LOG_FORMAT=json`.

## Rodar localmente

```powershell
cd C:\Users\kayky\Documents\Playground\baixaaqui-main-work
python -m pip install -r requirements.txt
copy .env.example .env
python scripts/diagnose.py
python bot.py
```

Preencha no `.env`: `API_ID`, `API_HASH`, `BOT_TOKEN` e `ADMIN_IDS`.

## Deploy VPS

Padrao recomendado:

```bash
sudo adduser --system --group --home /opt/baixaaqui baixa
sudo mkdir -p /opt/baixaaqui
sudo chown -R baixa:baixa /opt/baixaaqui
sudo -u baixa git clone SEU_REPO /opt/baixaaqui
cd /opt/baixaaqui
sudo -u baixa bash scripts/setup.sh
sudo -u baixa nano .env
sudo cp deploy/baixa_aquibot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now baixa_aquibot
journalctl -u baixa_aquibot -f
```

Diretorios esperados:

- `/opt/baixaaqui/data`
- `/opt/baixaaqui/downloads`
- `/opt/baixaaqui/public_files`
- `/opt/baixaaqui/cookies`
- `/opt/baixaaqui/logs`

## Cookies na VPS

Na VPS, YouTube/Instagram/TikTok podem bloquear IP de datacenter ou exigir login. Use cookies fixos do dono do bot. Nao coloque login/senha no codigo.

1. No seu computador, instale uma extensao confiavel como `Get cookies.txt LOCALLY`.
2. Entre na conta da plataforma no navegador.
3. Exporte cookies em formato Netscape/Mozilla `cookies.txt`.
4. Envie para a VPS:

```bash
scp youtube.txt usuario@vps:/opt/baixaaqui/cookies/youtube.txt
sudo chown baixa:baixa /opt/baixaaqui/cookies/youtube.txt
sudo chmod 600 /opt/baixaaqui/cookies/youtube.txt
```

Variaveis:

```env
YTDLP_COOKIES_YOUTUBE=/opt/baixaaqui/cookies/youtube.txt
YTDLP_COOKIES_INSTAGRAM=/opt/baixaaqui/cookies/instagram.txt
YTDLP_COOKIES_TIKTOK=/opt/baixaaqui/cookies/tiktok.txt
YTDLP_COOKIES_TWITTER=/opt/baixaaqui/cookies/twitter.txt
YTDLP_COOKIES_FACEBOOK=/opt/baixaaqui/cookies/facebook.txt
YTDLP_COOKIES_CRUNCHYROLL=/opt/baixaaqui/cookies/crunchyroll.txt
GALLERY_DL_CONFIG=/opt/baixaaqui/cookies/gallery-dl.conf
DOWNLOAD_PROXY=
```

Use `DOWNLOAD_PROXY` somente se a VPS estiver bloqueada por alguma plataforma; o valor e repassado para downloads diretos, yt-dlp, gallery-dl e aria2c.

Conteudo publico geralmente nao exige conta premium. Conteudo privado, stories, age gate, captcha, challenge, regiao bloqueada ou 429 pode exigir cookie valido. Cookies expiram; o diagnostico avisa quando passarem de `YTDLP_COOKIES_MAX_AGE_HOURS`.

## Testes de VPS

```bash
cd /opt/baixaaqui
. .venv/bin/activate
python scripts/diagnose.py
python -m yt_dlp --cookies /opt/baixaaqui/cookies/youtube.txt -F "URL_DO_YOUTUBE"
python -m gallery_dl --cookies /opt/baixaaqui/cookies/instagram.txt -J "URL_DO_INSTAGRAM"
curl http://127.0.0.1:8080/health
```

Se `PUBLIC_BASE_URL` usar `localhost`, IP privado ou dominio sem HTTPS publico, links gerados nao funcionarao fora da VPS. Configure Nginx/Caddy para servir `PUBLIC_FILES_DIR` em `/files`.

## Grupos

No BotFather, desative privacy mode ou torne o bot admin para ele ver links no grupo.

Variaveis principais:

```env
GROUP_AUTO_DOWNLOAD=true
GROUP_SILENT_MODE=true
GROUP_REPLY_ON_ERROR=false
GROUP_MAX_FILE_SIZE_MB=50
GROUP_WHITELIST_MODE=false
GROUP_ALLOWED_CHATS=
GROUP_BLOCKED_CHATS=
```

Comandos admin:

- `/allowgroup -1001234567890`
- `/bangroup -1001234567890`
- `/health`
- `/admin`

## Local Bot API

Para upload pesado, rode o Telegram Bot API server local e configure:

```env
SEND_BACKEND=auto
BOT_API_BASE_URL=http://127.0.0.1:8081
```

Com Local Bot API, o bot pode enviar arquivos por caminho local e reduzir muito o tempo de upload.

## Checklist rapido

- `python scripts/diagnose.py`
- `/health` no privado como admin
- YouTube normal: testar qualidade 360p/720p/1080p quando existir
- YouTube Music: testar audio
- TikTok video e slideshow
- Instagram Reels e carrossel com cookies
- X/Twitter com video/foto
- URL direta de imagem e arquivo
- Link temporario com `PUBLIC_BASE_URL` publico
- Grupo com `GROUP_SILENT_MODE=true`
