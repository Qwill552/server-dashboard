# Qwill Server Dashboard

Личный дашборд VPS: CPU, память, диск, сеть, uptime, температура CPU (если датчик доступен) и состояние Caddy. Интерфейс обновляется каждые 3 секунды. Приложение слушает только `127.0.0.1:5100`; публичный HTTPS и вход по паролю обеспечивает установленный на сервере Caddy.

Исходный локальный README сохранён без изменений в [README.original.md](README.original.md).

## Первая установка на Ubuntu 24.04

Все команды в этом разделе выполняете **вы**. Для разработки и деплоя не требуется передавать кому-либо пароль сервера или приватный SSH-ключ. Docker для этого приложения не нужен: сервис работает на хосте, чтобы показывать метрики самого VPS и статус `caddy.service`.

### 1. Подготовить сервер

Подключитесь к VPS привычным способом. Установите зависимости и склонируйте ветку с приложением:

```bash
sudo apt update
sudo apt install -y git rsync python3-venv
git clone --branch feat/dashboard --single-branch https://github.com/Qwill552/server-dashboard.git ~/server-dashboard-setup
sudo bash ~/server-dashboard-setup/scripts/bootstrap-server.sh
```

Скрипт создаст двух пользователей: `dashboard-app` запускает приложение без права входа, а `dashboard-deploy` принимает релизы от GitHub Actions без обычного `sudo`. Последнему разрешена только команда перезапуска `server-dashboard.service`. Существующий Caddyfile скрипт не меняет.

### 2. Создать ключ только для деплоя

На **своём Windows-компьютере** в PowerShell:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\dashboard_deploy" -C "server-dashboard-actions"
Get-Content "$env:USERPROFILE\.ssh\dashboard_deploy.pub"
```

Для автоматической работы GitHub Actions оставьте passphrase пустой. Скопируйте **только строку из `.pub`**. На VPS вставьте её одной строкой в файл:

```bash
sudo -u dashboard-deploy nano /home/dashboard-deploy/.ssh/authorized_keys
```

`bootstrap-server.sh` уже выставляет для файла нужные права. Приватный файл `dashboard_deploy` не отправляйте в чат и не добавляйте в репозиторий.

### 3. Задать адрес и секреты в GitHub

В репозитории откройте `Settings → Secrets and variables → Actions`. На вкладках **Secrets** и **Variables** создайте:

| Тип | Имя | Значение |
| --- | --- | --- |
| Repository variable | `DEPLOY_HOST` | `qwill-dashboard.mooo.com` |
| Repository secret | `DEPLOY_SSH_KEY` | Полное содержимое приватного файла `dashboard_deploy` с вашего компьютера |
| Repository secret | `DEPLOY_KNOWN_HOSTS` | Проверенный публичный SSH host key VPS в формате ниже |

Чтобы получить host key из **уже доверенного SSH-сеанса** на VPS, выполните:

```bash
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

Если вывод начинается с `ssh-ed25519 AAAA...`, значение `DEPLOY_KNOWN_HOSTS` должно быть одной строкой вида:

```text
qwill-dashboard.mooo.com ssh-ed25519 AAAA...
```

Вместо `AAAA...` вставьте точное поле ключа из вывода. Это не секрет, но оно должно быть получено с самого сервера; workflow не доверяет непроверенному ключу, найденному в сети.

### 4. Защитить сайт паролем в Caddy

На VPS выполните `caddy hash-password` и задайте длинный пароль в интерактивном приглашении. Полученный **хеш** вставьте в существующий блок Caddyfile:

```caddyfile
qwill-dashboard.mooo.com {
    basic_auth {
        qwill ВАШ_ХЕШ_ИЗ_CADDY_HASH_PASSWORD
    }
    reverse_proxy 127.0.0.1:5100
}
```

Затем проверьте и примените конфигурацию (если ваш файл расположен в `/etc/caddy/Caddyfile`):

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Пароль и его хеш не храните в публичном репозитории. Если установленная версия Caddy не знает директиву `basic_auth`, проверьте её версию: в старых версиях директива называлась `basicauth`.

### 5. Запустить первый деплой

Создайте pull request из `feat/dashboard` в `main`, посмотрите результат тестов и слейте его. Workflow проверит код, загрузит релиз по SSH, создаст Python-окружение на VPS, переключит сервис на новый релиз и проверит `/api/health`. При неудачном запуске он вернёт предыдущий релиз. Каждый следующий push в `main` повторит эту процедуру автоматически.

Откройте `https://qwill-dashboard.mooo.com`. Для диагностики на VPS:

```bash
sudo systemctl status server-dashboard.service
sudo journalctl -u server-dashboard.service -n 80 --no-pager
curl http://127.0.0.1:5100/api/health
```

## Что отображается

Метрики берутся из гостевой Ubuntu через `psutil`. Температура показывается только для датчика, явно распознанного как CPU. На многих VPS физические датчики хоста не передаются гостевой системе — тогда панель честно показывает «Н/Д». История графиков хранится в памяти приложения около 12 минут и начинается заново после перезапуска. Если сам Caddy остановится, сайт через этот домен станет недоступен; внешний мониторинг доступности можно добавить отдельно.

## Локальный запуск

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m dashboard
```

Откройте `http://127.0.0.1:5100`. В Windows используйте `.venv\Scripts\python.exe` вместо `.venv/bin/python`. Проверка: `python -m unittest discover -s tests -v` в окружении с установленным `psutil`.
