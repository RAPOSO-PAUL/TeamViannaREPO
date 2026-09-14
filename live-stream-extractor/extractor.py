import json
import re
import sys
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÃO
# ============================================================

SOURCE_URL = sys.argv[1]

results = {}


# Extensões que queremos procurar
MEDIA_EXTENSIONS = (
    ".m3u8",
    ".m3u",
    ".mpd",
    ".mp4",
    ".ts",
)

# MIME types conhecidos
HLS_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
)

DASH_TYPES = (
    "application/dash+xml",
)


# ============================================================
# UTILIDADES
# ============================================================

def valid_http_url(url):
    try:
        parsed = urlparse(url)

        return parsed.scheme in (
            "http",
            "https",
        )

    except Exception:
        return False


def normalize_url(url, base_url=None):

    if not url:
        return None

    url = url.strip()

    # Remove aspas acidentais
    url = url.strip("\"'")

    # Converte URL relativa em absoluta
    if base_url:
        url = urljoin(
            base_url,
            url
        )

    if not valid_http_url(url):
        return None

    return url


def classify_stream(url, content_type=""):

    value = (
        url + " " + content_type
    ).lower()

    if (
        ".m3u8" in value
        or "mpegurl" in value
    ):
        return "hls"

    if (
        ".mpd" in value
        or "dash+xml" in value
    ):
        return "dash"

    if ".m3u" in value:
        return "m3u"

    if ".mp4" in value:
        return "mp4"

    if ".ts" in value:
        return "mpeg-ts"

    if (
        url.lower().endswith("/file.txt")
        or "file.txt?" in url.lower()
    ):
        return "hls-file-txt"

    return "other"


def add_stream(
    url,
    content_type="",
    stream_type=None,
    source="network"
):

    url = normalize_url(url)

    if not url:
        return

    if not stream_type:
        stream_type = classify_stream(
            url,
            content_type
        )

    results[url] = {
        "url": url,
        "type": stream_type,
        "content_type": content_type,
        "source": source,
        "host": urlparse(url).netloc,
    }


# ============================================================
# DETECÇÃO DE PLAYLIST
# ============================================================

def is_hls_playlist(text):

    if not text:
        return False

    sample = text[:100000]

    return (
        "#EXTM3U" in sample
        or "#EXT-X-" in sample
    )


def is_dash_manifest(text):

    if not text:
        return False

    sample = text[:100000].lower()

    return (
        "<mpd" in sample
        or "<mpd " in sample
        or "urn:mpeg:dash" in sample
    )


# ============================================================
# EXTRAÇÃO DE URLS
# ============================================================

def extract_urls(text):

    if not text:
        return set()

    patterns = [

        # HLS
        r'https?://[^"\'<>\s]+\.m3u8(?:\?[^"\'<>\s]*)?',

        # M3U
        r'https?://[^"\'<>\s]+\.m3u(?:\?[^"\'<>\s]*)?',

        # DASH
        r'https?://[^"\'<>\s]+\.mpd(?:\?[^"\'<>\s]*)?',

        # FILE.TXT
        r'https?://[^"\'<>\s]+/file\.txt(?:\?[^"\'<>\s]*)?',

        # MP4
        r'https?://[^"\'<>\s]+\.mp4(?:\?[^"\'<>\s]*)?',

        # TS
        r'https?://[^"\'<>\s]+\.ts(?:\?[^"\'<>\s]*)?',
    ]

    found = set()

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE
        )

        for match in matches:

            url = normalize_url(match)

            if url:
                found.add(url)

    return found


# ============================================================
# ANALISAR RESPOSTA HTTP
# ============================================================

def inspect_response(
    url,
    content_type="",
    body=None
):

    if not url:
        return

    url = normalize_url(url)

    if not url:
        return

    lower_url = url.lower()
    lower_type = (
        content_type or ""
    ).lower()

    # --------------------------------------------------------
    # HLS pelo Content-Type
    # --------------------------------------------------------

    if any(
        mime in lower_type
        for mime in HLS_TYPES
    ):

        add_stream(
            url,
            content_type,
            "hls",
            "network"
        )

        return

    # --------------------------------------------------------
    # DASH pelo Content-Type
    # --------------------------------------------------------

    if any(
        mime in lower_type
        for mime in DASH_TYPES
    ):

        add_stream(
            url,
            content_type,
            "dash",
            "network"
        )

        return

    # --------------------------------------------------------
    # M3U8
    # --------------------------------------------------------

    if ".m3u8" in lower_url:

        add_stream(
            url,
            content_type,
            "hls",
            "network"
        )

        return

    # --------------------------------------------------------
    # MPD
    # --------------------------------------------------------

    if ".mpd" in lower_url:

        add_stream(
            url,
            content_type,
            "dash",
            "network"
        )

        return

    # --------------------------------------------------------
    # FILE.TXT
    # --------------------------------------------------------

    if (
        lower_url.endswith("/file.txt")
        or "file.txt?" in lower_url
    ):

        if body and is_hls_playlist(body):

            add_stream(
                url,
                content_type,
                "hls-file-txt",
                "network"
            )

        return

    # --------------------------------------------------------
    # Detectar playlist pelo conteúdo
    # --------------------------------------------------------

    if body:

        if is_hls_playlist(body):

            add_stream(
                url,
                content_type,
                "hls",
                "content"
            )

        elif is_dash_manifest(body):

            add_stream(
                url,
                content_type,
                "dash",
                "content"
            )


# ============================================================
# EXTRAIR PLAYLISTS DENTRO DE UMA RESPOSTA
# ============================================================

def inspect_body(
    body,
    base_url
):

    if not body:
        return

    for found in extract_urls(body):

        absolute = normalize_url(
            found,
            base_url
        )

        if absolute:

            add_stream(
                absolute,
                "",
                classify_stream(
                    absolute
                ),
                "embedded"
            )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=========================================="
    )
    print(
        "       LIVE STREAM EXTRACTOR"
    )
    print(
        "=========================================="
    )

    print(
        f"[+] URL: {SOURCE_URL}"
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(

            user_agent=(
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            ),

            viewport={
                "width": 1920,
                "height": 1080
            }
        )

        page = context.new_page()


        # ====================================================
        # NETWORK RESPONSE
        # ====================================================

        def on_response(response):

            try:

                url = response.url

                headers = response.headers

                content_type = (
                    headers.get(
                        "content-type",
                        ""
                    )
                )

                body = None

                # Não baixar corpos grandes
                # desnecessariamente.
                should_read = (

                    "text" in content_type.lower()

                    or "json" in content_type.lower()

                    or "mpegurl"
                    in content_type.lower()

                    or ".txt" in url.lower()

                    or ".m3u" in url.lower()

                    or ".mpd" in url.lower()
                )

                if should_read:

                    try:

                        body = response.text()

                    except Exception:

                        body = None


                inspect_response(
                    url,
                    content_type,
                    body
                )


                if body:

                    inspect_body(
                        body,
                        url
                    )


            except Exception as error:

                print(
                    f"[!] Erro response: {error}"
                )


        page.on(
            "response",
            on_response
        )


        # ====================================================
        # NETWORK REQUEST
        # ====================================================

        def on_request(request):

            try:

                url = request.url

                lower = url.lower()

                if (
                    ".m3u8" in lower
                    or ".m3u" in lower
                    or ".mpd" in lower
                    or "/file.txt" in lower
                ):

                    add_stream(
                        url,
                        "",
                        classify_stream(url),
                        "request"
                    )

            except Exception:
                pass


        page.on(
            "request",
            on_request
        )


        # ====================================================
        # ABRIR PÁGINA
        # ====================================================

        try:

            page.goto(
                SOURCE_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

        except Exception as error:

            print(
                f"[!] Falha ao abrir página: {error}"
            )


        # ====================================================
        # AGUARDAR PLAYER / JAVASCRIPT
        # ====================================================

        print(
            "[+] Aguardando carregamento do player..."
        )

        page.wait_for_timeout(
            15000
        )


        # ====================================================
        # HTML FINAL
        # ====================================================

        try:

            html = page.content()

            for url in extract_urls(
                html
            ):

                add_stream(
                    url,
                    "",
                    classify_stream(url),
                    "html"
                )

        except Exception as error:

            print(
                f"[!] Erro HTML: {error}"
            )


        # ====================================================
        # ELEMENTOS VIDEO/AUDIO
        # ====================================================

        try:

            elements = page.locator(
                "video, audio, source"
            ).all()

            for element in elements:

                for attribute in (
                    "src",
                    "data-src",
                    "data-url",
                    "data-file"
                ):

                    try:

                        value = (
                            element.get_attribute(
                                attribute
                            )
                        )

                        if value:

                            absolute = normalize_url(
                                value,
                                page.url
                            )

                            if absolute:

                                add_stream(
                                    absolute,
                                    "",
                                    classify_stream(
                                        absolute
                                    ),
                                    "media-element"
                                )

                    except Exception:
                        pass

        except Exception:
            pass


        browser.close()


    # ========================================================
    # RESULTADO
    # ========================================================

    output = {

        "source": SOURCE_URL,

        "count": len(results),

        "streams": list(
            results.values()
        )
    }


    with open(
        "streams.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False
        )


    print()
    print(
        "=========================================="
    )
    print(
        f"Streams encontrados: {len(results)}"
    )
    print(
        "=========================================="
    )


    for stream in results.values():

        print(
            f"[{stream['type']}] "
            f"{stream['url']}"
        )


if __name__ == "__main__":
    main()
