# Analise dos bots de referencia

Data: 2026-05-14

Objetivo: comparar bots de download por URL e absorver no Baixa Aqui apenas recursos compativeis com a arquitetura atual, sem copiar segredos, binarios, fluxos frageis ou codigo de contorno de DRM.

## Resumo executivo

O Baixa Aqui ja cobre boa parte do que os projetos externos fazem: Telethon, yt-dlp, gallery-dl, cookies por plataforma, aria2c, cache de metadados, cache de file_id, upload paralelo, diagnostico e modo grupo. As melhores oportunidades encontradas foram correcao do fluxo social, normalizacao segura de URL, comando rapido de audio, proxy configuravel e melhor documentacao operacional para VPS.

## Integrado agora

- Fluxo social corrigido em `bot.py`: links de YouTube, Instagram, TikTok, X, Spotify, Crunchyroll etc. deixam de cair como URL direta.
- `/mp3 <url>` e `/audio <url>`: comando rapido para baixar audio usando o pipeline social existente.
- Normalizacao de URL: remove `utm_*`, `si`, `feature` e `ref`, limpa pontuacao final e preserva parametros validos.
- Protecao contra hosts parecidos: `youtube.com.evil.example` nao passa como URL social.
- `DOWNLOAD_PROXY`: proxy opcional para downloads diretos, yt-dlp, gallery-dl e aria2c.
- Testes cobrindo normalizacao, host falso, cookie Crunchyroll e proxy em yt-dlp.

## Repos analisados

### aryanvikash/Youtube-Downloader-Bot

Stack: Pyrogram, youtube_dl antigo, FFmpeg.

Pontos uteis:
- Botoes de escolha entre audio, video e documento.
- Separacao entre envio como media e como documento.

Decisao:
- Nao portar codigo. Usa `youtube_dl` legado e parsing fragil de stdout.
- Ideia ja coberta no Baixa Aqui por botoes de social/direct/file e seletor de qualidade.

### KUpals001/youtube-downloader

Stack: Next.js, yt-dlp, FFmpeg, MusicBrainz/metadata.

Pontos uteis:
- Normalizacao de formatos via JSON do yt-dlp.
- SponsorBlock opcional.
- Metadata tagging para audio.
- Streaming de progresso estruturado.

Decisao:
- Integracao parcial futura: metadados de audio e SponsorBlock podem entrar depois.
- O bot atual ja usa JSON do yt-dlp e progresso.

### hitesh9624/YouTube-Playlist-Downloader

Stack: script Python, yt-dlp, FFmpeg, ThreadPoolExecutor.

Pontos uteis:
- `--flat-playlist` para listar playlist.
- Range `start/end`.
- Paralelismo por item.

Decisao:
- Nao integrar download de playlist em massa agora porque pode explodir fila, limite Telegram e storage.
- Futura melhoria: aceitar playlist com limite admin/configuravel e confirmar intervalo antes de baixar.

### shivamk21-ssk/InstagramPro-Toolkit

Stack: Windows batch, modulo compilado, instaloader.

Pontos uteis:
- Pouco aproveitavel no codigo aberto; parte central esta compilada.
- Ideia de usar instaloader para casos especificos do Instagram.

Decisao:
- Nao integrar. `gallery-dl` ja e mais adequado e transparente para fallback de Instagram.

### MelDxKviel/reels-downloader-bot

Stack: aiogram, yt-dlp, PostgreSQL, cookies, cache, inline mode.

Pontos uteis:
- Normalizacao segura de URL e remocao de tracking.
- Rejeicao de dominio look-alike.
- Comandos `/mp3`, `/voice`, `/gif`, `/round`.
- Cache por URL e file_id.
- Guia de cookies bem claro.

Decisao:
- Integrado agora: normalizacao segura e `/mp3`.
- Ja coberto: cache de file_id e cookies.
- Futuro: `/round`, `/gif` e inline mode exigem mais mudancas de UX/upload.

### shahadathakhand747/telegram-video-downloader-bot

Stack: Go, Telegram Bot API, yt-dlp, Docker.

Pontos uteis:
- Health check simples.
- Deploy Docker enxuto.
- Envio por URL direta do CDN quando possivel.

Decisao:
- Health check ja existe no Baixa Aqui.
- Envio por URL direta ja existe parcialmente via fast remote send/Bot API.
- Docker pode ser melhorado depois com base nessa abordagem.

### kalanakt/All-Url-Uploader

Stack: aiogram, yt-dlp, aiohttp, hachoir, thumbnails.

Pontos uteis:
- Parser de entrada `url|filename`.
- Proxy configuravel.
- Progresso de download direto com velocidade/ETA.
- Thumbnails por usuario.
- Metadata de video/audio antes do upload.

Decisao:
- Integrado agora: proxy configuravel.
- Ja coberto: thumbnails, metadata, progresso e `url|filename`.
- Futuro: suporte opcional a URL com usuario/senha se for realmente necessario.

### ToonTamilIndia/Crunchy-Bot-CLI

Stack: Pyrogram, API Crunchyroll, Widevine, mp4decrypt, FFmpeg.

Pontos uteis:
- Detalhes de UI para selecionar idioma/audio/subtitulo.
- Detalhes de nomenclatura e metadados.

Bloqueio:
- O fluxo principal usa PSSH/licenca Widevine e decriptacao DRM. Isso nao sera integrado.

Decisao:
- Integrar apenas deteccao, cookies e mensagens honestas de DRM.
- Para conteudo Crunchyroll com DRM, o bot deve responder que cookies autenticam, mas nao removem DRM.

### nimiology/spotify_downloader_telegram__bot

Stack: Telethon, Spotipy, YouTube Search, yt-dlp, eyed3, Genius.

Pontos uteis:
- Spotify como fonte de metadados.
- Busca no YouTube por faixa/artista e download de audio.
- Tagging de MP3 com capa, artista, album e letra.
- Cache via canal/banco para reuso.

Decisao:
- Nao integrar completo agora porque exige credenciais Spotify/Genius e politica clara de busca.
- Futura melhoria recomendada: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, resolver faixa/album/playlist para `ytsearch`, baixar audio e taggear com `mutagen`.

## Proximas integracoes recomendadas

1. Playlist YouTube com limite configuravel: `PLAYLIST_MAX_ITEMS`, confirmacao e range.
2. `/round` para video note de ate 60s.
3. `/gif` com limite de duracao/tamanho.
4. Spotify resolver opcional com credenciais e tagging MP3.
5. Dockerfile oficial do Baixa Aqui com healthcheck e volumes de cookies.
6. Guia de deploy VPS completo com `git pull`, cookies e systemd.
