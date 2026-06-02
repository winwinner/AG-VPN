# Hysteria2 VPS Panel

Веб-панель для управления пользователями [Hysteria2](https://hysteria.network/) — быстрого VPN-протокола поверх QUIC. Включает конфиг nginx с DPI-заглушкой и systemd-сервис.

## Что делает проект

- Показывает список пользователей и их трафик (upload / download) в реальном времени
- Позволяет добавлять и удалять пользователей прямо из браузера
- Генерирует строку подключения (`hysteria2://...`) для каждого пользователя — скопировать в один клик
- Nginx на 443 отдаёт страницу-заглушку для обхода DPI; панель живёт на порту 8080 (только localhost или через SSH-туннель)

## Структура

```
panel.py                — веб-панель (Python, порт 8080)
hysteria-panel.service  — systemd-сервис для панели
nginx-pokrascloud.conf  — конфиг nginx: TLS 1.2/1.3, HSTS, CSP, заглушка на 443
www/index.html          — страница-заглушка (отдаётся nginx на 443)
secrets.py.example      — шаблон для локальных переменных (Windows-скрипты)
Роутеры.bat             — ярлык: открывает веб-интерфейсы роутеров в Chrome
```

На сервере секреты хранятся в `/etc/hysteria-panel/secrets.env` (не в репо).

## Установка на VPS

**1. Скопировать файлы:**
```bash
cp panel.py /opt/hysteria-panel/panel.py
cp hysteria-panel.service /etc/systemd/system/
cp nginx-pokrascloud.conf /etc/nginx/sites-available/your-domain.conf
ln -s /etc/nginx/sites-available/your-domain.conf /etc/nginx/sites-enabled/
cp -r www /var/www/pokrascloud
```

**2. Создать файл с секретами:**
```bash
mkdir -p /etc/hysteria-panel
cat > /etc/hysteria-panel/secrets.env <<EOF
PANEL_USER=admin
PANEL_PASS=your-strong-password
PANEL_HOST=your-domain.example.com
PANEL_PORT=443
PANEL_SNI=your-domain.example.com
EOF
chmod 600 /etc/hysteria-panel/secrets.env
```

**3. Запустить:**
```bash
systemctl daemon-reload
systemctl enable --now hysteria-panel
nginx -t && systemctl reload nginx
```

## Использование

Панель доступна по адресу `http://<VPS-IP>:8080` или через SSH-туннель:

```bash
ssh -L 8080:127.0.0.1:8080 root@your-vps
# затем открыть http://localhost:8080
```

Войти с логином и паролем из `secrets.env`.

| Действие | Как |
|---|---|
| Добавить пользователя | Ввести имя (и опционально пароль) → **+ Добавить** |
| Удалить пользователя | Кнопка **Удалить** в строке пользователя |
| Скопировать строку подключения | Кнопка **Копировать** — вставить в клиент Hysteria2 |
| Обновить статистику трафика | Кнопка **↻ Обновить** |

Строку подключения вставить в любой клиент с поддержкой Hysteria2: [NekoBox](https://github.com/MatsuriDayo/NekoBoxForAndroid), [Hiddify](https://hiddify.com/), [v2rayN](https://github.com/2dust/v2rayN) и др.
