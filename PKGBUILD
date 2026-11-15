# Maintainer: av <av@localhost>
pkgname=whisper-station
pkgver=0.4.0
pkgrel=1
pkgdesc="Локальная диктовка для KDE Plasma 6 / Wayland: хоткей, HUD, вставка текста"
arch=('any')
# Заполнить адресом репозитория при публикации (AUR требует поле url).
url=""
license=('GPL-3.0-only')
depends=(
  'python'
  'pyside6'
  'python-dbus'
  'python-gobject'
  'pipewire'
  'libpulse'
  'wl-clipboard'
  'libnotify'
)
optdepends=(
  'ydotool: вставка через эмуляцию Ctrl+V (uinput)'
  'python-pip: установка окружения сервера, если в Python нет ensurepip'
)
options=('!strip')

# Пакет собирается из этого каталога: makepkg -f --nocheck
# Для AUR замените source на архив релиза, например:
#   source=("$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz")
source=()
sha256sums=()

package() {
  local libdir="$pkgdir/usr/lib/$pkgname"

  install -dm755 "$libdir"
  # -r, а не -a: владельца задаёт сам пакет, а сохранение owner из рабочего
  # каталога ломается там, где fakeroot недоступен (CI, контейнеры).
  cp -r "$startdir/whisper_station" "$libdir/"
  # Байткод не тащим в пакет: он пересоберётся при первом запуске.
  find "$libdir" -name '__pycache__' -type d -prune -exec rm -rf {} +
  # Репозиторий может иметь строгий umask (600/700) — в пакете права должны
  # быть обычными, иначе пользователь не прочитает модули.
  find "$libdir" -type d -exec chmod 755 {} +
  find "$libdir" -type f -exec chmod 644 {} +

  install -Dm755 /dev/stdin "$pkgdir/usr/bin/$pkgname" <<'WRAPPER'
#!/bin/sh
# Обёртка: код лежит в /usr/lib/whisper-station, а не в site-packages.
export PYTHONPATH="/usr/lib/whisper-station${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m whisper_station "$@"
WRAPPER

  install -Dm644 "$startdir/packaging/$pkgname.desktop" \
    "$pkgdir/usr/share/applications/$pkgname.desktop"
  install -Dm644 "$startdir/packaging/$pkgname.svg" \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/$pkgname.svg"
  install -d "$pkgdir/usr/share/$pkgname/sounds"
  install -m644 "$startdir/packaging/sounds/"*.wav \
    "$pkgdir/usr/share/$pkgname/sounds/"
  install -Dm644 "$startdir/README.md" \
    "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 "$startdir/README.ru.md" \
    "$pkgdir/usr/share/doc/$pkgname/README.ru.md"
  install -Dm644 "$startdir/LICENSE" \
    "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
