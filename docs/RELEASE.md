# Публикация 0.4.0 (CachyOS/Arch)

Что публикуем: исходники на GitHub + собранный пакет Arch. Другие дистрибутивы,
AUR и Flatpak — не в этом релизе.

## 1. Перед публикацией

```sh
make lint && make test            # 249 тестов, линт чистый
makepkg -f --nocheck              # пакет собирается из этой папки
bin/whisper-station doctor        # на живой машине всё зелёное
./install.sh --dry-run            # план установки для нового пользователя
```

- [ ] `CHANGELOG.md` содержит `## [0.4.0]`, версии в `pyproject.toml`, `PKGBUILD`
      и `whisper_station/__init__.py` совпадают (это проверяет `tests/test_version.py`).
- [ ] Скриншоты свежие: `QT_QPA_PLATFORM=offscreen python3 tools/screenshots.py`.
- [ ] `README.md` (английский) и `README.ru.md` описывают текущее поведение.
- [ ] `PKGBUILD`: поле `url` заполнено адресом репозитория (сейчас пустое).
- [ ] В `README.md` / `README.ru.md` установка, модель и ограничения описывают текущее
      поведение.

## 2. Репозиторий

```sh
git remote add origin git@github.com:<owner>/whisper-station.git
git push -u origin main
```

Репозиторий создавать пустым (без README и лицензии), иначе первый push конфликтует.

## 3. Тег и релиз

```sh
git tag -a v0.4.0 -m "whisper-station 0.4.0"
git push origin v0.4.0
```

Дальше на GitHub: **Releases → Draft a new release**. Это просто форма поверх тега,
ничего не создаётся до кнопки Publish. Заполнить нужно минимум:

1. **Choose a tag** — выбрать `v0.4.0` (он уже есть после `git push origin v0.4.0`).
2. **Release title** — `whisper-station 0.4.0` (можно оставить пустым, будет `v0.4.0`).
3. **Describe this release** — нажать **Generate release notes**: GitHub сам подставит
   список коммитов. Писать руками не нужно.
4. **Attach binaries** — перетащить только `whisper-station-0.4.0-1-any.pkg.tar.zst`.
   Архивы исходников (`Source code.zip/tar.gz`) GitHub добавляет сам, `git archive` не нужен.
5. **Publish release**.

Если описание хочется по-человечески, вот готовый текст:

```markdown
Первая публичная версия для CachyOS/Arch (KDE Plasma 6, Wayland).

- свой сервер распознавания: `whisper-station server install` (faster-whisper в отдельном venv)
- шесть моделей на выбор, GPU (CUDA) или CPU, `whisper-station model download`
- HUD с осциллограммой и живым предпросмотром, push-to-talk
- словарь терминов уходит в модель как prompt
- установка одной командой: `./install.sh`
```

## 4. Чистая проверка перед релизом (обязательно)

Полностью снести установленное и поставить заново скриптом — это ловит всё, что
забыли упаковать:

```sh
whisper-station server uninstall --yes
sudo pacman -R whisper-station
rm -rf ~/.config/whisper-station ~/.config/whisper-dictate \
       ~/.local/state/whisper-station ~/.local/share/whisper-station

cd ~/Documents/av-wisper-linux
./install.sh          # зависимости, пакет, сервер, модель, автозапуск, doctor
```

Затем проверить вживую: хоткей, HUD, `Esc`, вставка в обычное окно и терминал.

## 5. Проверка после публикации

```sh
git clone https://github.com/anton2901/whisper-station.git /tmp/ws-check
cd /tmp/ws-check && ./install.sh                # весь путь установки как у пользователя
whisper-station doctor
```

## 6. AUR (следующим шагом)

1. `PKGBUILD`: `source=("$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz")`,
   `sha256sums=('…')` из архива релиза; `url` — адрес репозитория.
2. `makepkg --printsrcinfo > .SRCINFO`, коммит `PKGBUILD` + `.SRCINFO` в отдельный
   AUR-репозиторий (`ssh://aur@aur.archlinux.org/whisper-station.git`).
3. Проверить `makepkg -f` в чистом chroot (`extra-x86_64-build`).
