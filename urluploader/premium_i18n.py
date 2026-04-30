from __future__ import annotations

from .html_text import h

SUPPORTED_LANGUAGES = {"pt", "en", "es"}


TEXTS: dict[str, dict[str, str]] = {
    "pt": {
        "welcome": (
            "<b>Olá, {name}.</b>\n"
            "<i>Seu hub premium para baixar, enviar, organizar e compartilhar mídias.</i>\n\n"
            "Envie um link ou arquivo. Eu cuido do resto com rapidez e capricho."
        ),
        "help": (
            "<b>Ajuda rápida</b>\n\n"
            "• Links sociais são baixados de forma inteligente.\n"
            "• URLs diretas são analisadas antes do envio.\n"
            "• Arquivos podem ser renomeados, receber capa, legenda e conversões.\n"
            "• Use <b>/cancelar</b> para limpar o fluxo atual."
        ),
        "menu_title": "<b>Central de controle</b>\nEscolha o que deseja fazer.",
        "menu_download": "<b>Baixar por link</b>\n<i>Envie um link de rede social. No privado eu mostro opções quando fizer sentido; em grupos entrego o resultado final sem poluir o chat.</i>",
        "menu_upload": "<b>Enviar por URL</b>\n<i>Envie uma URL direta de arquivo. Eu verifico nome, tamanho e tipo antes de baixar.</i>",
        "menu_tools": "<b>Ferramentas de mídia</b>\n<i>Envie vídeo, áudio, PDF, CBZ ou EPUB para renomear, editar legenda, definir capa ou converter.</i>",
        "menu_thumb": "<b>Capa padrão</b>\n<i>Envie uma imagem para salvar como capa padrão ou remova a capa atual.</i>\n\nStatus: {thumb}",
        "menu_links": "<b>Meus links</b>\n{items}",
        "menu_premium": "<b>Experiência premium</b>\n<i>Este bot foi pensado para velocidade, estabilidade e acabamento de produto, sem cobrança embutida.</i>",
        "link_empty": "<i>Você ainda não gerou links neste bot.</i>",
        "link_item": "• {filename} — {size}",
        "link_deleted": "<b>Link apagado</b>\n<i>Ele foi removido do seu histórico.</i>",
        "settings": "<b>Configurações</b>\n\nIdioma: {lang_name}\nCapa padrão: {thumb}\nModo: inteligente",
        "settings_home": "<b>Configurações</b>\n<i>Ajuste idioma, capa padrão e preferências do seu espaço.</i>",
        "settings_language": "<b>Idioma</b>\n<i>Escolha como deseja ver toda a interface.</i>",
        "empty_tasks": "<b>Minhas tarefas</b>\nVocê não tem tarefas em andamento agora.",
        "rate_limited": (
            "<b>Calma um instante.</b>\n\n"
            "<i>Você enviou muitas ações em pouco tempo.\n"
            "Tente novamente em alguns segundos.</i>"
        ),
        "maintenance": "<b>Manutenção ativa</b>\n<i>O bot está pausado temporariamente. Tente novamente em breve.</i>",
        "not_admin": "<b>Acesso restrito</b>\n<i>Este painel está disponível apenas para administradores.</i>",
        "social_disabled": "<b>Links sociais indisponíveis</b>\n<i>Esse tipo de download está desativado neste ambiente.</i>",
        "analyzing_link": "<b>Analisando link</b>\n<i>Estou verificando tipo, tamanho e opções disponíveis.</i>",
        "analyze_failed": "Não consegui analisar esse link com segurança.",
        "social_sending": "<b>Enviando sua mídia</b>\n<i>Assim que concluir, removo este aviso.</i>",
        "quality_card": (
            "<b>Escolha a qualidade</b>\n"
            "<i>Selecione a melhor opção para este vídeo.</i>\n\n"
            "{title}"
        ),
        "social_card": (
            "<b>Mídia encontrada</b>\n\n"
            "Tipo: {kind}\n"
            "Autor: {author}\n"
            "Título: {title}\n"
            "Duração: {duration}\n"
            "Itens: {items}\n"
            "Qualidade: {quality}"
        ),
        "direct_card": (
            "<b>Arquivo remoto detectado</b>\n\n"
            "Nome: {filename}\n"
            "Tamanho: {size}\n"
            "Tipo: {kind}\n\n"
            "<i>Escolha como deseja enviar.</i>"
        ),
        "file_card": (
            "<b>O que deseja fazer com este arquivo?</b>\n\n"
            "Nome: {filename}\n"
            "Tamanho: {size}\n"
            "Tipo: {kind}"
        ),
        "photo_card": (
            "<b>O que deseja fazer com esta imagem?</b>\n\n"
            "<i>No privado, eu posso gerar um link com prévia automaticamente.</i>"
        ),
        "thumb_request": "<b>Capa</b>\nEnvie uma imagem para usar como capa desta tarefa.",
        "thumb_default_request": "<b>Definir capa padrão</b>\n<i>Envie a imagem que você quer usar como capa nos próximos envios.</i>",
        "thumb_saved": "<b>Capa salva</b>\n<i>Ela será usada apenas quando você escolher.</i>",
        "thumb_removed": "<b>Capa removida</b>\n<i>Sua capa padrão foi apagada.</i>",
        "thumb_missing": "<b>Nenhuma capa padrão</b>\nEnvie uma imagem e escolha salvar como padrão.",
        "rename_request": "<b>Renomear arquivo</b>\nEnvie o novo nome com extensão. Exemplo: <code>video-final.mp4</code>",
        "caption_request": "<b>Editar legenda</b>\nEnvie a nova legenda. Para remover, envie <code>limpar</code>.",
        "context_cleaned": "<b>Contexto limpo</b>\n<i>Pode começar uma nova tarefa.</i>",
        "cancelled": "<b>Tarefa cancelada</b>\n<i>Nada foi alterado.</i>",
        "queued": "<b>Tarefa adicionada</b>\n<i>Vou processar assim que houver uma vaga.</i>",
        "stage_analyzing": "<b>Analisando</b>\n<i>Preparando as melhores opções.</i>",
        "stage_preparing": "<b>Preparando sua mídia</b>\n<i>Isso pode levar alguns instantes.</i>",
        "stage_downloading": "<b>Baixando</b>\n{progress}",
        "stage_converting": "<b>Convertendo</b>\n<i>Ajustando o arquivo para o formato escolhido.</i>",
        "stage_uploading": "<b>Enviando</b>\n{progress}",
        "stage_linking": "<b>Gerando link</b>\n<i>Seu arquivo está sendo preparado para compartilhamento.</i>",
        "done": "<b>Concluído</b>\n<i>Pronto para usar.</i>",
        "link_done": "<b>Link gerado com sucesso</b>\n<i>Seu arquivo já está pronto para compartilhar.</i>\n\n{url}",
        "error_human": "<b>Não consegui concluir</b>\n{reason}\n\n<i>Você pode tentar novamente ou escolher outra opção.</i>",
        "expired": "<b>Essa ação expirou</b>\nEnvie o link ou arquivo novamente para continuar.",
        "invalid_name": "<b>Nome inválido</b>\nUse um nome simples, com extensão e sem caracteres proibidos.",
        "unsupported": "<b>Formato não suportado</b>\nEsse arquivo não pode ser usado nessa ação.",
        "conversion_unavailable": "<b>Conversão indisponível</b>\n<i>Instale as dependências opcionais e tente novamente.</i>",
        "image_link_error": "<b>Não consegui gerar o link da imagem</b>\n<i>Verifique a conexão do host de imagem e tente novamente.</i>",
        "language_changed": "<b>Idioma atualizado</b>\n<i>A interface já está usando o idioma escolhido.</i>",
        "unexpected_media_error": "Ocorreu uma falha inesperada ao processar a mídia.",
        "original_file_missing": "Não encontrei o arquivo original.",
        "telegram_file_download_failed": "Não consegui baixar esse arquivo do Telegram.",
        "link_generation_failed": "Não consegui gerar o link para esse arquivo.",
        "link_requires_public_base": "O storage local não está público. Defina PUBLIC_BASE_URL com um domínio acessível.",
        "link_local_disabled": "O link local está desativado neste servidor. Ative um storage externo para gerar links de arquivo.",
        "youtube_auth_required": "O YouTube bloqueou este servidor. Configure YTDLP_COOKIES_FILE ou YTDLP_COOKIES_FROM_BROWSER para liberar a análise.",
        "facebook_auth_required": "O Facebook exigiu login para esse link. Tente um link público direto ou configure cookies do navegador para o yt-dlp.",
        "ffmpeg_missing": "FFmpeg e ffprobe não estão disponíveis neste servidor. Instale o pacote ffmpeg na VPS para processar vídeos.",
        "state_on": "ativa",
        "state_off": "não definida",
        "unknown_value": "não informado",
        "unknown_title": "sem título",
        "quality_auto": "automática",
        "kind_video": "vídeo",
        "kind_audio": "áudio",
        "kind_image": "imagem",
        "kind_file": "arquivo",
        "kind_album": "álbum",
        "admin_overview": (
            "<b>Painel administrativo</b>\n\n"
            "Usuários: {users}\n"
            "Jobs registrados: {jobs}\n"
            "Links gerados: {links}\n"
            "Disco temporário: {temp_size}\n"
            "Arquivos públicos: {public_size}\n"
            "Tarefas ativas: {active}"
        ),
        "broadcast_prompt": "<b>Broadcast</b>\nEnvie a mensagem que deseja publicar para os usuários.",
        "label_download": "Download",
        "label_upload": "Upload",
        "btn_link_download": "📥 Baixar vídeo",
        "btn_audio": "🎵 Extrair áudio",
        "btn_images": "🖼️ Baixar imagem(ns)",
        "btn_all": "📦 Baixar tudo",
        "btn_file": "📂 Enviar como arquivo",
        "btn_video": "🎬 Enviar como vídeo",
        "btn_audio_send": "🎵 Enviar como áudio",
        "btn_rename": "📝 Renomear",
        "btn_caption": "✏️ Editar legenda",
        "btn_thumb": "🖼️ Definir capa",
        "btn_temp_thumb": "🖼️ Usar nesta tarefa",
        "btn_save_thumb": "💾 Salvar capa padrão",
        "btn_resend": "📤 Reenviar",
        "btn_generate_link": "🔗 Gerar link",
        "btn_open": "🌐 Abrir link",
        "btn_delete_link": "🗑️ Apagar link",
        "btn_back": "⬅️ Voltar",
        "btn_set_thumb": "🖼️ Definir capa",
        "btn_remove_thumb": "🗑️ Remover capa",
        "btn_language": "🌍 Idioma",
        "btn_cover_settings": "🖼️ Capa",
        "btn_retry": "♻️ Tentar novamente",
        "btn_more": "⚙️ Mais opções",
        "btn_cancel": "❌ Cancelar",
        "btn_clean": "🧹 Limpar contexto",
        "btn_details": "🔎 Ver detalhes",
        "btn_convert_pdf": "📄 Converter para PDF",
        "btn_convert_cbz": "📚 Converter para CBZ",
        "btn_convert_epub": "📖 Converter para EPUB",
        "btn_best_quality": "⚡ Melhor qualidade",
        "btn_menu_download": "📥 Baixar por link",
        "btn_menu_upload": "📤 Enviar por URL",
        "btn_menu_tools": "🎬 Ferramentas de mídia",
        "btn_menu_thumb": "🖼️ Capa",
        "btn_menu_tasks": "🗂️ Minhas tarefas",
        "btn_menu_links": "🔗 Meus links",
        "btn_menu_settings": "⚙️ Configurações",
        "btn_menu_help": "❓ Ajuda",
        "btn_menu_premium": "👑 Premium",
        "btn_lang_pt": "🇧🇷 Português",
        "btn_lang_en": "🇺🇸 English",
        "btn_lang_es": "🇪🇸 Español",
    },
    "en": {
        "welcome": "<b>Hello, {name}.</b>\n<i>Your premium hub to download, upload, organize, and share media.</i>\n\nSend a link or file. I will handle it quickly and cleanly.",
        "help": "<b>Quick help</b>\n\n• Social links are handled intelligently.\n• Direct URLs are inspected before upload.\n• Files can be renamed, captioned, covered, and converted.\n• Use <b>/cancel</b> to clear the current flow.",
        "menu_title": "<b>Control center</b>\nChoose what you want to do.",
        "menu_download": "<b>Download by link</b>\n<i>Send a social link. In private I show options when needed; in groups I deliver only the final result.</i>",
        "menu_upload": "<b>Upload by URL</b>\n<i>Send a direct file URL. I inspect name, size, and type before downloading.</i>",
        "menu_tools": "<b>Media tools</b>\n<i>Send video, audio, PDF, CBZ, or EPUB to rename, edit caption, set cover, or convert.</i>",
        "menu_thumb": "<b>Default cover</b>\n<i>Send an image to save as your default cover or remove the current one.</i>\n\nStatus: {thumb}",
        "menu_links": "<b>My links</b>\n{items}",
        "menu_premium": "<b>Premium experience</b>\n<i>This bot is built for speed, stability, and polish, with no paywall built into the flow.</i>",
        "link_empty": "<i>You have not created any links yet.</i>",
        "link_item": "• {filename} — {size}",
        "link_deleted": "<b>Link deleted</b>\n<i>It was removed from your history.</i>",
        "settings": "<b>Settings</b>\n\nLanguage: {lang_name}\nDefault cover: {thumb}\nMode: smart",
        "settings_home": "<b>Settings</b>\n<i>Adjust language, default cover, and core preferences.</i>",
        "settings_language": "<b>Language</b>\n<i>Choose how you want to see the whole interface.</i>",
        "empty_tasks": "<b>My tasks</b>\nYou have no active tasks right now.",
        "rate_limited": "<b>Slow down for a moment.</b>\n\n<i>Too many actions in a short time.\nTry again in a few seconds.</i>",
        "maintenance": "<b>Maintenance mode</b>\n<i>The bot is temporarily paused. Try again soon.</i>",
        "not_admin": "<b>Restricted access</b>\n<i>This panel is available only to administrators.</i>",
        "social_disabled": "<b>Social links unavailable</b>\n<i>This download path is disabled in the current environment.</i>",
        "analyzing_link": "<b>Analyzing link</b>\n<i>Checking type, size, and available options.</i>",
        "analyze_failed": "I could not inspect this link safely.",
        "social_sending": "<b>Sending your media</b>\n<i>I will remove this notice when it is done.</i>",
        "quality_card": "<b>Choose quality</b>\n<i>Select the best option for this video.</i>\n\n{title}",
        "social_card": "<b>Media found</b>\n\nType: {kind}\nAuthor: {author}\nTitle: {title}\nDuration: {duration}\nItems: {items}\nQuality: {quality}",
        "direct_card": "<b>Remote file detected</b>\n\nName: {filename}\nSize: {size}\nType: {kind}\n\n<i>Choose how to send it.</i>",
        "file_card": "<b>What do you want to do with this file?</b>\n\nName: {filename}\nSize: {size}\nType: {kind}",
        "photo_card": "<b>What do you want to do with this image?</b>\n\n<i>In private chat, I can create a preview link automatically.</i>",
        "thumb_request": "<b>Cover</b>\nSend an image to use as this task cover.",
        "thumb_default_request": "<b>Set default cover</b>\n<i>Send the image you want to use as your default cover in future uploads.</i>",
        "thumb_saved": "<b>Cover saved</b>\n<i>It will be used only when you choose it.</i>",
        "thumb_removed": "<b>Cover removed</b>\n<i>Your default cover was deleted.</i>",
        "thumb_missing": "<b>No default cover</b>\nSend an image and choose save as default.",
        "rename_request": "<b>Rename file</b>\nSend the new name with extension. Example: <code>final-video.mp4</code>",
        "caption_request": "<b>Edit caption</b>\nSend the new caption. To remove it, send <code>clear</code>.",
        "context_cleaned": "<b>Context cleared</b>\n<i>You can start a new task.</i>",
        "cancelled": "<b>Task cancelled</b>\n<i>Nothing was changed.</i>",
        "queued": "<b>Task queued</b>\n<i>I will process it as soon as a slot is available.</i>",
        "stage_analyzing": "<b>Analyzing</b>\n<i>Preparing the best options.</i>",
        "stage_preparing": "<b>Preparing your media</b>\n<i>This may take a moment.</i>",
        "stage_downloading": "<b>Downloading</b>\n{progress}",
        "stage_converting": "<b>Converting</b>\n<i>Adjusting the file to the selected format.</i>",
        "stage_uploading": "<b>Uploading</b>\n{progress}",
        "stage_linking": "<b>Creating link</b>\n<i>Your file is being prepared for sharing.</i>",
        "done": "<b>Done</b>\n<i>Ready to use.</i>",
        "link_done": "<b>Link created successfully</b>\n<i>Your file is ready to share.</i>\n\n{url}",
        "error_human": "<b>I could not finish</b>\n{reason}\n\n<i>You can retry or choose another option.</i>",
        "expired": "<b>This action expired</b>\nSend the link or file again to continue.",
        "invalid_name": "<b>Invalid name</b>\nUse a simple filename with extension and no forbidden characters.",
        "unsupported": "<b>Unsupported format</b>\nThis file cannot be used for that action.",
        "conversion_unavailable": "<b>Conversion unavailable</b>\n<i>Install optional dependencies and try again.</i>",
        "image_link_error": "<b>I could not create the image link</b>\n<i>Check the image host connection and try again.</i>",
        "language_changed": "<b>Language updated</b>\n<i>The interface is already using your selection.</i>",
        "unexpected_media_error": "An unexpected error happened while processing the media.",
        "original_file_missing": "I could not find the original file.",
        "telegram_file_download_failed": "I could not download this file from Telegram.",
        "link_generation_failed": "I could not create a link for this file.",
        "link_requires_public_base": "Local storage is not public. Set PUBLIC_BASE_URL to an externally reachable domain.",
        "link_local_disabled": "Local link storage is disabled on this server. Enable external storage to create file links.",
        "youtube_auth_required": "YouTube blocked this server. Configure YTDLP_COOKIES_FILE or YTDLP_COOKIES_FROM_BROWSER to continue.",
        "facebook_auth_required": "Facebook required login for this link. Try a direct public URL or configure browser cookies for yt-dlp.",
        "ffmpeg_missing": "FFmpeg and ffprobe are not available on this server. Install the ffmpeg package on the VPS to process videos.",
        "state_on": "active",
        "state_off": "not set",
        "unknown_value": "not available",
        "unknown_title": "untitled",
        "quality_auto": "automatic",
        "kind_video": "video",
        "kind_audio": "audio",
        "kind_image": "image",
        "kind_file": "file",
        "kind_album": "album",
        "admin_overview": "<b>Admin panel</b>\n\nUsers: {users}\nJobs: {jobs}\nLinks: {links}\nTemp disk: {temp_size}\nPublic files: {public_size}\nActive tasks: {active}",
        "broadcast_prompt": "<b>Broadcast</b>\nSend the message you want to publish to users.",
        "label_download": "Download",
        "label_upload": "Upload",
        "btn_link_download": "📥 Download video",
        "btn_audio": "🎵 Extract audio",
        "btn_images": "🖼️ Download image(s)",
        "btn_all": "📦 Download all",
        "btn_file": "📂 Send as file",
        "btn_video": "🎬 Send as video",
        "btn_audio_send": "🎵 Send as audio",
        "btn_rename": "📝 Rename",
        "btn_caption": "✏️ Edit caption",
        "btn_thumb": "🖼️ Set cover",
        "btn_temp_thumb": "🖼️ Use in this task",
        "btn_save_thumb": "💾 Save default cover",
        "btn_resend": "📤 Resend",
        "btn_generate_link": "🔗 Create link",
        "btn_open": "🌐 Open link",
        "btn_delete_link": "🗑️ Delete link",
        "btn_back": "⬅️ Back",
        "btn_set_thumb": "🖼️ Set cover",
        "btn_remove_thumb": "🗑️ Remove cover",
        "btn_language": "🌍 Language",
        "btn_cover_settings": "🖼️ Cover",
        "btn_retry": "♻️ Retry",
        "btn_cancel": "❌ Cancel",
        "btn_convert_pdf": "📄 Convert to PDF",
        "btn_convert_cbz": "📚 Convert to CBZ",
        "btn_convert_epub": "📖 Convert to EPUB",
        "btn_best_quality": "⚡ Best quality",
        "btn_menu_download": "📥 Download by link",
        "btn_menu_upload": "📤 Upload by URL",
        "btn_menu_tools": "🎬 Media tools",
        "btn_menu_thumb": "🖼️ Cover",
        "btn_menu_tasks": "🗂️ My tasks",
        "btn_menu_links": "🔗 My links",
        "btn_menu_settings": "⚙️ Settings",
        "btn_menu_help": "❓ Help",
        "btn_menu_premium": "👑 Premium",
        "btn_lang_pt": "🇧🇷 Português",
        "btn_lang_en": "🇺🇸 English",
        "btn_lang_es": "🇪🇸 Español",
    },
    "es": {
        "welcome": "<b>Hola, {name}.</b>\n<i>Tu centro premium para descargar, subir, organizar y compartir medios.</i>\n\nEnvía un enlace o archivo. Lo preparo con rapidez y cuidado.",
        "help": "<b>Ayuda rápida</b>\n\n• Los enlaces sociales se procesan de forma inteligente.\n• Las URL directas se analizan antes de subir.\n• Los archivos pueden renombrarse, llevar portada, leyenda y conversiones.\n• Usa <b>/cancelar</b> para limpiar el flujo actual.",
        "menu_title": "<b>Centro de control</b>\nElige lo que quieres hacer.",
        "menu_download": "<b>Descargar por enlace</b>\n<i>Envía un enlace social. En privado muestro opciones cuando vale la pena; en grupos entrego solo el resultado final.</i>",
        "menu_upload": "<b>Subir por URL</b>\n<i>Envía una URL directa de archivo. Reviso nombre, tamaño y tipo antes de descargar.</i>",
        "menu_tools": "<b>Herramientas de medios</b>\n<i>Envía video, audio, PDF, CBZ o EPUB para renombrar, editar leyenda, definir portada o convertir.</i>",
        "menu_thumb": "<b>Portada predeterminada</b>\n<i>Envía una imagen para guardar como portada predeterminada o elimina la portada actual.</i>\n\nEstado: {thumb}",
        "menu_links": "<b>Mis enlaces</b>\n{items}",
        "menu_premium": "<b>Experiencia premium</b>\n<i>Este bot fue diseñado para velocidad, estabilidad y buen acabado, sin cobros integrados.</i>",
        "link_empty": "<i>Aún no has generado enlaces en este bot.</i>",
        "link_item": "• {filename} — {size}",
        "link_deleted": "<b>Enlace eliminado</b>\n<i>Fue removido de tu historial.</i>",
        "settings": "<b>Configuración</b>\n\nIdioma: {lang_name}\nPortada predeterminada: {thumb}\nModo: inteligente",
        "settings_home": "<b>Configuración</b>\n<i>Ajusta idioma, portada predeterminada y preferencias clave.</i>",
        "settings_language": "<b>Idioma</b>\n<i>Elige cómo quieres ver toda la interfaz.</i>",
        "empty_tasks": "<b>Mis tareas</b>\nNo tienes tareas activas ahora.",
        "rate_limited": "<b>Espera un momento.</b>\n\n<i>Enviaste muchas acciones en poco tiempo.\nInténtalo de nuevo en unos segundos.</i>",
        "maintenance": "<b>Mantenimiento activo</b>\n<i>El bot está pausado temporalmente. Inténtalo de nuevo pronto.</i>",
        "not_admin": "<b>Acceso restringido</b>\n<i>Este panel está disponible solo para administradores.</i>",
        "social_disabled": "<b>Enlaces sociales no disponibles</b>\n<i>Este tipo de descarga está desactivado en este entorno.</i>",
        "analyzing_link": "<b>Analizando enlace</b>\n<i>Verificando tipo, tamaño y opciones disponibles.</i>",
        "analyze_failed": "No pude analizar este enlace con seguridad.",
        "social_sending": "<b>Enviando tu medio</b>\n<i>Quitaré este aviso al terminar.</i>",
        "quality_card": "<b>Elige la calidad</b>\n<i>Selecciona la mejor opción para este video.</i>\n\n{title}",
        "social_card": "<b>Medio encontrado</b>\n\nTipo: {kind}\nAutor: {author}\nTítulo: {title}\nDuración: {duration}\nElementos: {items}\nCalidad: {quality}",
        "direct_card": "<b>Archivo remoto detectado</b>\n\nNombre: {filename}\nTamaño: {size}\nTipo: {kind}\n\n<i>Elige cómo enviarlo.</i>",
        "file_card": "<b>¿Qué quieres hacer con este archivo?</b>\n\nNombre: {filename}\nTamaño: {size}\nTipo: {kind}",
        "photo_card": "<b>¿Qué quieres hacer con esta imagen?</b>\n\n<i>En privado, puedo crear un enlace con vista previa automáticamente.</i>",
        "thumb_request": "<b>Portada</b>\nEnvía una imagen para usar como portada de esta tarea.",
        "thumb_default_request": "<b>Definir portada predeterminada</b>\n<i>Envía la imagen que quieres usar como portada en futuros envíos.</i>",
        "thumb_saved": "<b>Portada guardada</b>\n<i>Se usará solo cuando la elijas.</i>",
        "thumb_removed": "<b>Portada eliminada</b>\n<i>Tu portada predeterminada fue borrada.</i>",
        "thumb_missing": "<b>Sin portada predeterminada</b>\nEnvía una imagen y elige guardar como predeterminada.",
        "rename_request": "<b>Renombrar archivo</b>\nEnvía el nuevo nombre con extensión. Ejemplo: <code>video-final.mp4</code>",
        "caption_request": "<b>Editar leyenda</b>\nEnvía la nueva leyenda. Para borrarla, envía <code>limpiar</code>.",
        "context_cleaned": "<b>Contexto limpio</b>\n<i>Puedes iniciar una nueva tarea.</i>",
        "cancelled": "<b>Tarea cancelada</b>\n<i>Nada fue alterado.</i>",
        "queued": "<b>Tarea en cola</b>\n<i>La procesaré cuando haya un cupo disponible.</i>",
        "stage_analyzing": "<b>Analizando</b>\n<i>Preparando las mejores opciones.</i>",
        "stage_preparing": "<b>Preparando tu medio</b>\n<i>Esto puede tardar unos instantes.</i>",
        "stage_downloading": "<b>Descargando</b>\n{progress}",
        "stage_converting": "<b>Convirtiendo</b>\n<i>Ajustando el archivo al formato elegido.</i>",
        "stage_uploading": "<b>Subiendo</b>\n{progress}",
        "stage_linking": "<b>Generando enlace</b>\n<i>Tu archivo se está preparando para compartir.</i>",
        "done": "<b>Concluido</b>\n<i>Listo para usar.</i>",
        "link_done": "<b>Enlace generado con éxito</b>\n<i>Tu archivo ya está listo para compartir.</i>\n\n{url}",
        "error_human": "<b>No pude concluir</b>\n{reason}\n\n<i>Puedes intentar de nuevo o elegir otra opción.</i>",
        "expired": "<b>Esta acción expiró</b>\nEnvía el enlace o archivo nuevamente para continuar.",
        "invalid_name": "<b>Nombre inválido</b>\nUsa un nombre simple, con extensión y sin caracteres prohibidos.",
        "unsupported": "<b>Formato no soportado</b>\nEste archivo no puede usarse en esa acción.",
        "conversion_unavailable": "<b>Conversión no disponible</b>\n<i>Instala las dependencias opcionales e inténtalo de nuevo.</i>",
        "image_link_error": "<b>No pude generar el enlace de la imagen</b>\n<i>Revisa la conexión con el host de imágenes e inténtalo de nuevo.</i>",
        "language_changed": "<b>Idioma actualizado</b>\n<i>La interfaz ya está usando tu selección.</i>",
        "unexpected_media_error": "Ocurrió una falla inesperada al procesar el medio.",
        "original_file_missing": "No encontré el archivo original.",
        "telegram_file_download_failed": "No pude descargar este archivo desde Telegram.",
        "link_generation_failed": "No pude generar un enlace para este archivo.",
        "link_requires_public_base": "El storage local no es público. Define PUBLIC_BASE_URL con un dominio accesible.",
        "link_local_disabled": "El almacenamiento local de enlaces está desactivado en este servidor. Activa un storage externo para generar enlaces de archivo.",
        "youtube_auth_required": "YouTube bloqueó este servidor. Configura YTDLP_COOKIES_FILE o YTDLP_COOKIES_FROM_BROWSER para continuar.",
        "facebook_auth_required": "Facebook pidió inicio de sesión para este enlace. Prueba una URL pública directa o configura cookies del navegador para yt-dlp.",
        "ffmpeg_missing": "FFmpeg y ffprobe no están disponibles en este servidor. Instala el paquete ffmpeg en la VPS para procesar videos.",
        "state_on": "activa",
        "state_off": "no definida",
        "unknown_value": "no informado",
        "unknown_title": "sin título",
        "quality_auto": "automática",
        "kind_video": "video",
        "kind_audio": "audio",
        "kind_image": "imagen",
        "kind_file": "archivo",
        "kind_album": "álbum",
        "admin_overview": "<b>Panel administrativo</b>\n\nUsuarios: {users}\nJobs: {jobs}\nEnlaces: {links}\nDisco temporal: {temp_size}\nArchivos públicos: {public_size}\nTareas activas: {active}",
        "broadcast_prompt": "<b>Broadcast</b>\nEnvía el mensaje que deseas publicar a los usuarios.",
        "label_download": "Descarga",
        "label_upload": "Subida",
        "btn_link_download": "📥 Descargar video",
        "btn_audio": "🎵 Extraer audio",
        "btn_images": "🖼️ Descargar imagen(es)",
        "btn_all": "📦 Descargar todo",
        "btn_file": "📂 Enviar como archivo",
        "btn_video": "🎬 Enviar como video",
        "btn_audio_send": "🎵 Enviar como audio",
        "btn_rename": "📝 Renombrar",
        "btn_caption": "✏️ Editar leyenda",
        "btn_thumb": "🖼️ Definir portada",
        "btn_temp_thumb": "🖼️ Usar en esta tarea",
        "btn_save_thumb": "💾 Guardar portada predeterminada",
        "btn_resend": "📤 Reenviar",
        "btn_generate_link": "🔗 Generar enlace",
        "btn_open": "🌐 Abrir enlace",
        "btn_delete_link": "🗑️ Borrar enlace",
        "btn_back": "⬅️ Volver",
        "btn_set_thumb": "🖼️ Definir portada",
        "btn_remove_thumb": "🗑️ Eliminar portada",
        "btn_language": "🌍 Idioma",
        "btn_cover_settings": "🖼️ Portada",
        "btn_retry": "♻️ Reintentar",
        "btn_cancel": "❌ Cancelar",
        "btn_convert_pdf": "📄 Convertir a PDF",
        "btn_convert_cbz": "📚 Convertir a CBZ",
        "btn_convert_epub": "📖 Convertir a EPUB",
        "btn_best_quality": "⚡ Mejor calidad",
        "btn_menu_download": "📥 Descargar por enlace",
        "btn_menu_upload": "📤 Subir por URL",
        "btn_menu_tools": "🎬 Herramientas de medios",
        "btn_menu_thumb": "🖼️ Portada",
        "btn_menu_tasks": "🗂️ Mis tareas",
        "btn_menu_links": "🔗 Mis enlaces",
        "btn_menu_settings": "⚙️ Configuración",
        "btn_menu_help": "❓ Ayuda",
        "btn_menu_premium": "👑 Premium",
        "btn_lang_pt": "🇧🇷 Português",
        "btn_lang_en": "🇺🇸 English",
        "btn_lang_es": "🇪🇸 Español",
    },
}


TEXTS["pt"].update(
    {
        "welcome": (
            "<b>Ol\u00e1, {name}.</b>\n"
            "<i>Seu espa\u00e7o para baixar, organizar e compartilhar m\u00eddia com rapidez e acabamento premium.</i>\n\n"
            "Envie um link ou arquivo para continuar."
        ),
        "help": "<b>Como usar</b>\n\n\u2022 Envie um link para eu analisar a m\u00eddia.\n\u2022 Envie arquivo, foto, v\u00eddeo ou \u00e1udio para abrir a\u00e7\u00f5es compat\u00edveis.\n\u2022 Use <b>/cancelar</b> para encerrar o fluxo atual.",
        "menu_title": "<b>Painel principal</b>\n<i>Escolha um atalho ou envie uma m\u00eddia para continuar.</i>",
        "menu_download": "<b>Baixar por link</b>\n<i>Envie um link no privado. Eu detecto o tipo do conte\u00fado antes de mostrar as a\u00e7\u00f5es certas.</i>",
        "menu_upload": "<b>Enviar por URL</b>\n<i>Envie uma URL direta. Se for simples e compat\u00edvel, eu uso o caminho mais r\u00e1pido.</i>",
        "menu_tools": "<b>Ferramentas</b>\n<i>Envie foto, v\u00eddeo, \u00e1udio ou documento para reenviar, renomear, gerar link ou converter.</i>",
        "menu_thumb": "<b>Capa padr\u00e3o</b>\n<i>Defina uma capa para usar nos seus envios quando fizer sentido.</i>\n\nStatus: {thumb}",
        "menu_links": "<b>Meus links</b>\n{items}",
        "settings": "<b>Configura\u00e7\u00f5es</b>\n\nIdioma: {lang_name}\nCapa padr\u00e3o: {thumb}\nFluxo: inteligente",
        "empty_tasks": "<b>Minhas tarefas</b>\n<i>Nenhuma tarefa recente por aqui.</i>",
        "rate_limited": "<b>Calma um instante.</b>\n\n<i>Voc\u00ea enviou muitas a\u00e7\u00f5es em pouco tempo.\nTente novamente em alguns segundos.</i>",
        "analyzing_link": "<b>Analisando</b>\n<i>Estou identificando o tipo do conte\u00fado e o caminho mais r\u00e1pido.</i>",
        "social_sending": "<b>Preparando a m\u00eddia</b>\n<i>Assim que ficar pronta, eu entrego aqui.</i>",
        "direct_card": "<b>Arquivo detectado</b>\n\nNome: {filename}\nTamanho: {size}\nTipo: {kind}\n\n<i>Escolha apenas uma a\u00e7\u00e3o compat\u00edvel.</i>",
        "file_card": "<b>Arquivo recebido</b>\n\nNome: {filename}\nTamanho: {size}\nTipo: {kind}",
        "photo_card": "<b>Imagem recebida</b>\n\n<i>Posso enviar como foto, manter original como arquivo ou gerar um link.</i>",
        "queued": "<b>Na fila</b>\n<i>Assim que abrir uma vaga, eu continuo daqui.</i>",
        "done": "<b>Conclu\u00eddo</b>\n<i>Tudo pronto para uso.</i>",
        "link_done": "<b>Link pronto</b>\n<i>Seu arquivo j\u00e1 pode ser compartilhado.</i>\n\n{url}",
        "error_human": "<b>N\u00e3o consegui concluir</b>\n{reason}\n\n<i>Voc\u00ea pode tentar novamente ou escolher outra a\u00e7\u00e3o.</i>",
        "analyze_failed": "N\u00e3o consegui analisar esse link com seguran\u00e7a.",
        "link_generation_failed": "N\u00e3o consegui gerar um link est\u00e1vel para esse arquivo.",
        "link_local_disabled": "O link local est\u00e1 desativado neste servidor. Ative um storage externo para gerar links de arquivo.",
        "youtube_auth_required": "O YouTube bloqueou este servidor. Configure YTDLP_COOKIES_FILE ou YTDLP_COOKIES_FROM_BROWSER para liberar a an\u00e1lise.",
        "instagram_auth_required": "O Instagram exigiu login para esse link. Configure cookies do navegador para continuar.",
        "facebook_auth_required": "O Facebook exigiu login para esse link. Tente um link p\u00fablico direto ou configure cookies do navegador para o yt-dlp.",
        "ffmpeg_missing": "FFmpeg e ffprobe n\u00e3o est\u00e3o dispon\u00edveis neste servidor. Instale o pacote ffmpeg na VPS para processar v\u00eddeos.",
        "youtube_audio_missing": "Esse v\u00eddeo voltou sem \u00e1udio. Tente outra qualidade ou verifique o FFmpeg do servidor.",
        "tasks_title": "<b>Minhas tarefas</b>",
        "task_item": "\u2022 {title} \u2014 <i>{status}</i>",
        "job_status_queued": "na fila",
        "job_status_running": "em andamento",
        "job_status_done": "conclu\u00edda",
        "job_status_failed": "com falha",
        "job_status_cancelled": "cancelada",
        "btn_send_photo": "\U0001f5bc\ufe0f Enviar como foto",
        "btn_download_media": "\U0001f4e5 Baixar m\u00eddia",
    }
)

TEXTS["en"].update(
    {
        "welcome": (
            "<b>Hello, {name}.</b>\n"
            "<i>Your space to download, organize, and share media with speed and premium polish.</i>\n\n"
            "Send a link or file to continue."
        ),
        "help": "<b>How it works</b>\n\n\u2022 Send a link and I inspect it first.\n\u2022 Send a file, photo, video, or audio and I will show only compatible actions.\n\u2022 Use <b>/cancel</b> to stop the current flow.",
        "menu_title": "<b>Main panel</b>\n<i>Choose a shortcut or send media to continue.</i>",
        "menu_download": "<b>Download by link</b>\n<i>Send a link in private chat. I classify the content before showing the right actions.</i>",
        "menu_upload": "<b>Send by URL</b>\n<i>Send a direct URL. When possible, I use the fastest safe path.</i>",
        "menu_tools": "<b>Tools</b>\n<i>Send a photo, video, audio file, or document to resend, rename, link, or convert it.</i>",
        "menu_thumb": "<b>Default cover</b>\n<i>Set a cover to reuse on compatible uploads.</i>\n\nStatus: {thumb}",
        "settings": "<b>Settings</b>\n\nLanguage: {lang_name}\nDefault cover: {thumb}\nFlow: smart",
        "empty_tasks": "<b>My tasks</b>\n<i>No recent tasks right now.</i>",
        "rate_limited": "<b>Hold on a second.</b>\n\n<i>I received too many actions in a short time.\nPlease try again in a few seconds.</i>",
        "analyzing_link": "<b>Inspecting</b>\n<i>I am identifying the content type and the fastest safe route.</i>",
        "social_sending": "<b>Preparing your media</b>\n<i>I will deliver it here as soon as it is ready.</i>",
        "direct_card": "<b>File detected</b>\n\nName: {filename}\nSize: {size}\nType: {kind}\n\n<i>Choose a compatible action.</i>",
        "file_card": "<b>File received</b>\n\nName: {filename}\nSize: {size}\nType: {kind}",
        "photo_card": "<b>Image received</b>\n\n<i>I can send it as a photo, keep the original file, or create a link.</i>",
        "queued": "<b>Queued</b>\n<i>I will continue as soon as a slot becomes available.</i>",
        "done": "<b>Done</b>\n<i>Everything is ready.</i>",
        "link_done": "<b>Link ready</b>\n<i>Your file is ready to share.</i>\n\n{url}",
        "error_human": "<b>I could not finish this</b>\n{reason}\n\n<i>You can retry or choose another action.</i>",
        "analyze_failed": "I could not inspect this link safely.",
        "link_generation_failed": "I could not create a stable link for this file.",
        "link_local_disabled": "Local link storage is disabled on this server. Enable external storage to create file links.",
        "youtube_auth_required": "YouTube blocked this server. Configure YTDLP_COOKIES_FILE or YTDLP_COOKIES_FROM_BROWSER to continue.",
        "instagram_auth_required": "Instagram required login for this link. Configure browser cookies to continue.",
        "facebook_auth_required": "Facebook required login for this link. Try a direct public URL or configure browser cookies for yt-dlp.",
        "ffmpeg_missing": "FFmpeg and ffprobe are not available on this server. Install the ffmpeg package on the VPS to process videos.",
        "youtube_audio_missing": "This video came back without audio. Try another quality or verify FFmpeg on the server.",
        "tasks_title": "<b>My tasks</b>",
        "task_item": "\u2022 {title} \u2014 <i>{status}</i>",
        "job_status_queued": "queued",
        "job_status_running": "running",
        "job_status_done": "done",
        "job_status_failed": "failed",
        "job_status_cancelled": "cancelled",
        "btn_send_photo": "\U0001f5bc\ufe0f Send as photo",
        "btn_download_media": "\U0001f4e5 Download media",
    }
)

TEXTS["es"].update(
    {
        "welcome": (
            "<b>Hola, {name}.</b>\n"
            "<i>Tu espacio para descargar, organizar y compartir medios con rapidez y acabado premium.</i>\n\n"
            "Env\u00eda un enlace o archivo para continuar."
        ),
        "help": "<b>C\u00f3mo funciona</b>\n\n\u2022 Env\u00eda un enlace y primero lo analizo.\n\u2022 Env\u00eda una foto, video, audio o archivo y mostrar\u00e9 solo acciones compatibles.\n\u2022 Usa <b>/cancelar</b> para cerrar el flujo actual.",
        "menu_title": "<b>Panel principal</b>\n<i>Elige un atajo o env\u00eda un medio para continuar.</i>",
        "menu_download": "<b>Descargar por enlace</b>\n<i>Env\u00eda un enlace en privado. Detecto el tipo de contenido antes de mostrar las acciones correctas.</i>",
        "menu_upload": "<b>Enviar por URL</b>\n<i>Env\u00eda una URL directa. Cuando se puede, uso la ruta m\u00e1s r\u00e1pida y segura.</i>",
        "menu_tools": "<b>Herramientas</b>\n<i>Env\u00eda foto, video, audio o documento para reenviar, renombrar, enlazar o convertir.</i>",
        "menu_thumb": "<b>Portada predeterminada</b>\n<i>Define una portada para reutilizarla en env\u00edos compatibles.</i>\n\nEstado: {thumb}",
        "settings": "<b>Configuraci\u00f3n</b>\n\nIdioma: {lang_name}\nPortada predeterminada: {thumb}\nFlujo: inteligente",
        "empty_tasks": "<b>Mis tareas</b>\n<i>No hay tareas recientes ahora mismo.</i>",
        "rate_limited": "<b>Un momento.</b>\n\n<i>Recib\u00ed demasiadas acciones en poco tiempo.\nInt\u00e9ntalo de nuevo en unos segundos.</i>",
        "analyzing_link": "<b>Analizando</b>\n<i>Estoy identificando el tipo de contenido y la ruta m\u00e1s r\u00e1pida.</i>",
        "social_sending": "<b>Preparando tu medio</b>\n<i>Lo entregar\u00e9 aqu\u00ed en cuanto est\u00e9 listo.</i>",
        "direct_card": "<b>Archivo detectado</b>\n\nNombre: {filename}\nTama\u00f1o: {size}\nTipo: {kind}\n\n<i>Elige una acci\u00f3n compatible.</i>",
        "file_card": "<b>Archivo recibido</b>\n\nNombre: {filename}\nTama\u00f1o: {size}\nTipo: {kind}",
        "photo_card": "<b>Imagen recibida</b>\n\n<i>Puedo enviarla como foto, mantener el original como archivo o generar un enlace.</i>",
        "queued": "<b>En cola</b>\n<i>Continuar\u00e9 en cuanto haya un espacio disponible.</i>",
        "done": "<b>Listo</b>\n<i>Todo est\u00e1 preparado.</i>",
        "link_done": "<b>Enlace listo</b>\n<i>Tu archivo ya se puede compartir.</i>\n\n{url}",
        "error_human": "<b>No pude completarlo</b>\n{reason}\n\n<i>Puedes reintentar o elegir otra acci\u00f3n.</i>",
        "analyze_failed": "No pude analizar este enlace con seguridad.",
        "link_generation_failed": "No pude generar un enlace estable para este archivo.",
        "link_local_disabled": "El almacenamiento local de enlaces est\u00e1 desactivado en este servidor. Activa un storage externo para generar enlaces de archivo.",
        "youtube_auth_required": "YouTube bloque\u00f3 este servidor. Configura YTDLP_COOKIES_FILE o YTDLP_COOKIES_FROM_BROWSER para continuar.",
        "instagram_auth_required": "Instagram pidi\u00f3 inicio de sesi\u00f3n para este enlace. Configura cookies del navegador para continuar.",
        "facebook_auth_required": "Facebook pidi\u00f3 inicio de sesi\u00f3n para este enlace. Prueba una URL p\u00fablica directa o configura cookies del navegador para yt-dlp.",
        "ffmpeg_missing": "FFmpeg y ffprobe no est\u00e1n disponibles en este servidor. Instala el paquete ffmpeg en la VPS para procesar videos.",
        "youtube_audio_missing": "Este video lleg\u00f3 sin audio. Prueba otra calidad o verifica FFmpeg en el servidor.",
        "tasks_title": "<b>Mis tareas</b>",
        "task_item": "\u2022 {title} \u2014 <i>{status}</i>",
        "job_status_queued": "en cola",
        "job_status_running": "en curso",
        "job_status_done": "lista",
        "job_status_failed": "con fallo",
        "job_status_cancelled": "cancelada",
        "btn_send_photo": "\U0001f5bc\ufe0f Enviar como foto",
        "btn_download_media": "\U0001f4e5 Descargar medio",
    }
)

TEXTS["pt"].update(
    {
        "auth_required": "Esse conteudo exige login/cookies validos. O admin pode configurar cookies fixos no .env.",
        "platform_blocked": "A plataforma bloqueou temporariamente este servidor. Tente novamente mais tarde ou configure cookies na VPS.",
        "download_timeout": "A plataforma demorou demais para responder. Interrompi a tarefa para manter o bot estavel.",
        "upload_failed": "O Telegram recusou o envio depois de algumas tentativas. Tente de novo em alguns minutos.",
        "group_allowed": "<b>Grupo liberado</b>\n<code>{chat_id}</code> ja pode usar o modo automatico.",
        "group_blocked": "<b>Grupo bloqueado</b>\n<code>{chat_id}</code> nao recebera downloads automaticos.",
    }
)

TEXTS["en"].update(
    {
        "auth_required": "This content requires valid login/cookies. The admin can configure fixed cookies in .env.",
        "platform_blocked": "The platform temporarily blocked this server. Try again later or configure cookies on the VPS.",
        "download_timeout": "The platform took too long to respond. I stopped the task to keep the bot stable.",
        "upload_failed": "Telegram rejected the upload after a few retries. Try again in a few minutes.",
        "group_allowed": "<b>Group allowed</b>\n<code>{chat_id}</code> can now use automatic mode.",
        "group_blocked": "<b>Group blocked</b>\n<code>{chat_id}</code> will not receive automatic downloads.",
    }
)

TEXTS["es"].update(
    {
        "auth_required": "Este contenido requiere login/cookies validas. El admin puede configurar cookies fijas en .env.",
        "platform_blocked": "La plataforma bloqueo temporalmente este servidor. Intentalo mas tarde o configura cookies en la VPS.",
        "download_timeout": "La plataforma tardo demasiado en responder. Detuve la tarea para mantener estable el bot.",
        "upload_failed": "Telegram rechazo el envio despues de algunos intentos. Intentalo de nuevo en unos minutos.",
        "group_allowed": "<b>Grupo permitido</b>\n<code>{chat_id}</code> ya puede usar el modo automatico.",
        "group_blocked": "<b>Grupo bloqueado</b>\n<code>{chat_id}</code> no recibira descargas automaticas.",
    }
)


for lang in ("en", "es"):
    for key, value in TEXTS["pt"].items():
        TEXTS[lang].setdefault(key, value)


def normalize_language(language: str | None, fallback: str = "pt") -> str:
    if not language:
        return fallback
    code = language.lower().split("-", 1)[0]
    return code if code in SUPPORTED_LANGUAGES else fallback


def tx(language: str, key: str, **values: object) -> str:
    text = TEXTS.get(normalize_language(language), TEXTS["pt"]).get(key, TEXTS["pt"].get(key, key))
    safe_values = {name: h(value) for name, value in values.items()}
    return text.format(**safe_values)
