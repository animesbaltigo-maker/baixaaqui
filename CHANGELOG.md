# Changelog

## Produção VPS

- Adicionada validação de cookies Netscape/Mozilla por plataforma.
- Adicionado diagnóstico de VPS via `/health` no chat admin e `scripts/diagnose.py`.
- Adicionado logging rotativo e opção de formato JSON.
- Adicionado modo de grupo silencioso com allow/ban por admin.
- Adicionada proteção SSRF para URLs diretas.
- Adicionados retries com backoff no upload Telegram e hosts de imagem.
- Adicionado limite de `PendingTarget` em memória para reduzir vazamento em alto volume.
- Adicionadas variáveis de tuning para yt-dlp, grupos, logs, jobs e branding.
