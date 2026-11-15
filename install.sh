#!/usr/bin/env bash
# Установка whisper-station на CachyOS/Arch: зависимости, пакет, сервер, модель.
#
#   ./install.sh                 # всё по умолчанию: CUDA если есть, модель по устройству
#   ./install.sh --cpu           # без CUDA, модель small
#   ./install.sh --model small   # конкретная модель
#   ./install.sh --dry-run       # только показать, что будет сделано
#
# Скрипт идемпотентен: уже установленное пропускает.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS=(pyside6 python-dbus python-gobject pipewire pipewire-audio wl-clipboard libnotify ydotool)
CUDA=auto            # auto|yes|no
MODEL=""             # пусто — выбрать по устройству
AUTOSTART=yes
DRY_RUN=no
ASSUME_YES=no

# Команды до установки пакета: запускаем из репозитория, чтобы не поймать
# старую установленную версию (bin/ сам выставляет PYTHONPATH).
WS="$REPO_DIR/bin/whisper-station"

# JSON-поля из CLI: grep по всему выводу ловит лишнее (например, "configured").
json_field() {
    python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get(sys.argv[1]))' "$1"
}

model_installed() {
    "$WS" model status 2>/dev/null \
        | python3 -c 'import json,sys; data=json.load(sys.stdin); print(sys.argv[1] in data.get("installed", []))' "$MODEL" \
        | grep -q True
}

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

run() {
    if [ "$DRY_RUN" = yes ]; then
        printf '   + %s\n' "$*"
    else
        "$@"
    fi
}

usage() {
    sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --cuda) CUDA=yes ;;
        --cpu) CUDA=no ;;
        --model) MODEL="${2:?--model требует имя}"; shift ;;
        --no-autostart) AUTOSTART=no ;;
        --dry-run) DRY_RUN=yes ;;
        -y|--yes) ASSUME_YES=yes ;;
        -h|--help) usage ;;
        *) die "Неизвестный аргумент: $1 (см. --help)" ;;
    esac
    shift
done

# --- проверки окружения ------------------------------------------------
[ "$(id -u)" -eq 0 ] && die "Не запускайте от root: пакет соберётся с root-правами."

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case " ${ID:-} ${ID_LIKE:-} " in
        *arch*) ;;
        *)
            warn "Похоже, это не Arch-based дистрибутив (${PRETTY_NAME:-неизвестно})."
            warn "Проект проверен только на CachyOS/Arch + KDE Plasma 6 + Wayland."
            [ "$ASSUME_YES" = yes ] || read -r -p "Продолжить? [y/N] " answer
            [ "${answer:-n}" = y ] || exit 1
            ;;
    esac
fi

if [ -z "${XDG_SESSION_TYPE:-}" ] || [ "${XDG_SESSION_TYPE}" != "wayland" ]; then
    warn "Сессия не Wayland (${XDG_SESSION_TYPE:-нет}): хоткей и вставка рассчитаны на Wayland."
fi

command -v makepkg >/dev/null || die "Нет makepkg: поставьте base-devel (sudo pacman -S base-devel)."
command -v pacman >/dev/null || die "Нет pacman — это не Arch."

# --- CUDA ---------------------------------------------------------------
if [ "$CUDA" = auto ]; then
    if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
        CUDA=yes
    elif [ -e /dev/nvidiactl ]; then
        CUDA=yes
    else
        CUDA=no
    fi
fi
[ "$CUDA" = yes ] && [ "$MODEL" = "" ] && MODEL="large-v3-turbo"
[ "$CUDA" = no ] && [ "$MODEL" = "" ] && MODEL="small"

say "План: CUDA=$CUDA, модель=$MODEL, автозапуск=$AUTOSTART, каталог=$REPO_DIR"

if [ -f "$HOME/.config/whisper-dictate/config.toml" ]; then
    warn "Найден старый конфиг ~/.config/whisper-dictate — настройки перенесутся из него."
    warn "Для чистого старта удалите: ~/.config/whisper-dictate ~/.config/whisper-station"
fi

# Старый демон держит сокет и работает старым кодом — перед обновлением гасим.
say "Останавливаю запущенный экземпляр"
run "$WS" quit

# --- 1. зависимости -----------------------------------------------------
say "Зависимости"
missing=$(pacman -T "${DEPS[@]}" 2>/dev/null || true)
if [ -n "$missing" ]; then
    # shellcheck disable=SC2086
    run sudo pacman -S --needed --noconfirm $missing
else
    echo "   всё уже стоит"
fi

# --- 2. пакет -----------------------------------------------------------
say "Пакет whisper-station"
version=$(sed -n 's/^pkgver=//p' "$REPO_DIR/PKGBUILD")
installed=$(pacman -Q whisper-station 2>/dev/null | awk '{print $2}' || true)
if [ "$installed" = "$version-1" ]; then
    echo "   уже установлен $installed"
else
    ( cd "$REPO_DIR" && run makepkg -f --nocheck )
    pkg=$(ls -1t "$REPO_DIR"/whisper-station-"$version"-*.pkg.tar.zst | head -1)
    run sudo pacman -U --noconfirm "$pkg"
fi

# --- 3. окружение сервера ----------------------------------------------
say "Окружение сервера (faster-whisper)"
if [ "$("$WS" server status | json_field installed)" = "True" ]; then
    if [ "$CUDA" = yes ] && [ "$("$WS" server status | json_field cuda)" != "True" ]; then
        run "$WS" server install --cuda
    else
        echo "   уже установлено"
    fi
elif [ "$CUDA" = yes ]; then
    run "$WS" server install --cuda
else
    run "$WS" server install
fi

# --- 4. модель ----------------------------------------------------------
say "Модель $MODEL"
if model_installed; then
    echo "   уже скачана"
else
    run "$WS" model download --name "$MODEL" --yes
fi

# --- 5. автозапуск ------------------------------------------------------
if [ "$AUTOSTART" = yes ]; then
    say "Автозапуск при входе"
    run "$WS" autostart on
fi

# --- 6. проверка --------------------------------------------------------
say "Проверка окружения"
if [ "$DRY_RUN" = yes ]; then
    echo "   + whisper-station doctor"
elif ! "$WS" doctor; then
    warn "doctor нашёл замечания — смотрите вывод выше."
fi

say "Готово"
cat <<EOF
Запуск:            whisper-station            (иконка в трее, хоткей по умолчанию Meta+Alt+D)
Настройки:         whisper-station settings   (хоткей, модель, вставка)
Лог:               whisper-station log
Повторная проверка: whisper-station doctor
EOF
