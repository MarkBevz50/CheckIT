# RUNBOOK: staging і продакшн CheckIT

Покрокова інструкція для чистого VPS з Ubuntu 24.04 LTS: підготовка сервера, перший деплой вручну, оновлення, логи, зупинка. Бекапи й автоматичний деплой додаються пізніше (E7.5, E7.6), тут лише тимчасова команда бекапу.

Усі команди нижче виконуються на сервері, якщо не сказано інше. `$DOMAIN` це домен із `.env.staging`.

## 0. Розмір сервера

| Сценарій | RAM | vCPU | Диск | Примітка |
| --- | --- | --- | --- | --- |
| Лише staging | 4 ГБ | 2 | 40 ГБ | **мінімум**; свопфайл обов'язковий (розділ 1.6) |
| **Staging і prod на одному сервері** | **8 ГБ** | **4** | **80 ГБ** | **рекомендовано** |

Типові ліміти пам'яті в `docker-compose.prod.yml` розраховані на 4 ГБ (db 512 МБ, redis 192 МБ, backend 1,5 ГБ, frontend 64 МБ, caddy 128 МБ). На 8 ГБ підніміть їх змінними в `.env.staging`, наприклад `BACKEND_MEM_LIMIT=3g`, `DB_MEM_LIMIT=1g`. Регіон: ЄС. Збірка образу backend (Tesseract, LibreOffice) і обробка великих скан-PDF найбільше навантажують пам'ять: саме для цього потрібен своп.

## 1. Підготовка чистої Ubuntu 24.04

### 1.1 Оновлення
Перший вхід під `root` або користувачем, якого дав провайдер (за ключем).
```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot            # якщо оновилось ядро; потім увійдіть знову
```

### 1.2 Користувач для деплою
```bash
sudo adduser deploy                     # задайте пароль: він потрібен лише для sudo, вхід по SSH за паролем буде вимкнено
sudo usermod -aG sudo deploy
sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
# скопіюйте свій відкритий ключ (з ноутбука виконайте: ssh-copy-id deploy@<IP-сервера>)
# або вручну додайте його рядок у /home/deploy/.ssh/authorized_keys (права 600, власник deploy)
```
Перевірте вхід **з окремого терміналу**: `ssh deploy@<IP-сервера>`. Далі працюйте під `deploy`.

### 1.3 SSH лише за ключем
Файл-доповнення має називатися `00-…`: sshd бере перше знайдене значення параметра, а образи провайдерів часто мають `50-cloud-init.conf` з `PasswordAuthentication yes`.
```bash
sudo tee /etc/ssh/sshd_config.d/00-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowUsers deploy
MaxAuthTries 3
EOF
sudo sshd -t && sudo systemctl reload ssh
sudo sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin|allowusers|kbdinteractiveauthentication)'
```
**Не закривайте поточну сесію**, доки з нового терміналу не перевірите `ssh deploy@<IP-сервера>` (вхід має працювати) і `ssh -o PubkeyAuthentication=no deploy@<IP-сервера>` (має відмовити). Порт 22 лишається стандартним.

### 1.4 Фаєрвол
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw limit 22/tcp          # SSH з обмеженням частоти спроб
sudo ufw allow 80/tcp          # HTTP (виклик Let's Encrypt і перенаправлення на HTTPS)
sudo ufw allow 443/tcp         # HTTPS
sudo ufw allow 443/udp         # HTTP/3
sudo ufw enable
sudo ufw status verbose
```
**Важливо:** порти, опубліковані Docker, **обходять `ufw`** (офіційне застереження документації Docker). Тому `docker-compose.prod.yml` публікує назовні лише Caddy (80 і 443), а база, Redis, backend і frontend доступні тільки всередині мережі compose. Не додавайте `ports:` до цих сервісів.

### 1.5 Автоматичні оновлення безпеки
```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades      # відповідь: Yes
```

### 1.6 Свопфайл (обов'язково для VPS на 4 ГБ)
Збірка образу та LibreOffice/Tesseract можуть вичерпати пам'ять. Розмір 2–4 ГБ (для 4 ГБ RAM візьміть 4 ГБ).
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf
sudo sysctl --system
swapon --show && free -h
```
Якщо файлова система не підтримує `fallocate` для свопу (деякі btrfs/ZFS), створіть файл через `sudo dd if=/dev/zero of=/swapfile bs=1M count=4096`, далі ті самі кроки з `chmod`.

### 1.7 Docker Engine
Кроки з офіційної документації (https://docs.docker.com/engine/install/ubuntu/, метод apt-репозиторію):
```bash
# GPG-ключ Docker
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# репозиторій
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo docker run hello-world
```
Далі дайте `deploy` доступ до Docker і перевірте версію Compose (потрібна **не нижче 2.24**, оверлей використовує `!reset`):
```bash
sudo usermod -aG docker deploy     # група docker дає практично права root: лише для довіреного користувача
# вийдіть і зайдіть знову, щоб група застосувалась
docker compose version
```

### 1.8 Інструменти для перевірки
```bash
sudo apt install -y git python3-requests
```

## 2. Спершу перевірте магазини (головний ризик E0.6)

Магазини можуть блокувати запити з IP дата-центрів. Це перевіряється **до** деплою, одним скриптом, без збірки образів.
```bash
git clone https://github.com/MarkBevz50/CheckIT.git
cd CheckIT && git checkout dev
python3 scripts/check_sources.py --show-ip
```
Скрипт запускає справжні парсери застосунку й для кожного магазину повертає вердикт `OK`, `ЗАБЛОКОВАНО`, `МЕРЕЖА`, `ПАРСЕР ЗЛАМАНИЙ` або `ПОМИЛКА` (код виходу 0 лише коли всі `OK`). **Скопіюйте абзац з кінця виводу в `PLAN/DIPLOMA_NOTES.md`.** Якщо будь-який магазин `ЗАБЛОКОВАНО`, зупиніться й вирішуйте разом: запасні шляхи (закупівельні ціни з Prozorro, E4.1) описано в `PLAN/Plan.md`.

## 3. DNS

У A-записі (і AAAA, якщо сервер має IPv6) домену `$DOMAIN` має стояти IP сервера. Перевірка з ноутбука або сервера:
```bash
dig +short $DOMAIN        # має показати IP сервера; без цього Let's Encrypt не видасть сертифікат
```

## 4. Перший деплой вручну

```bash
cd ~/CheckIT
cp .env.staging.example .env.staging
chmod 600 .env.staging
nano .env.staging
```
Заповніть змінні (шаблон пояснює кожну). **Усі секрети нові**, не з локального `.env`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"   # SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(24))"   # POSTGRES_PASSWORD
```
Для **першого** запуску вкажіть тестовий ACME-сервер, щоб не впертись у ліміти Let's Encrypt (сертифікат тоді не довірений браузерами):
```
ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory
```
Перевірка файла і запуск:
```bash
python3 scripts/check_env_staging.py             # має надрукувати OK
alias dc='docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.prod.yml'
dc config -q && echo "compose OK"
dc up -d --build                                  # перша збірка 5-10 хвилин; міграції бази виконуються самі при старті backend
dc ps                                             # усі сервіси healthy
dc logs --tail=50 caddy                           # має бути рядок про успішно отриманий сертифікат
curl -kI https://$DOMAIN                          # -k, бо тестовий сертифікат
```
Коли все працює, **очистіть** `ACME_CA` у `.env.staging` і застосуйте: `dc up -d` (Caddy отримає справжній сертифікат). Перевірте в браузері замочок і `curl -I https://$DOMAIN` без `-k`.

Перевірки приймання (результати запишіть у `PLAN/DIPLOMA_NOTES.md`):
```bash
# 1. назовні відкриті лише 80 і 443 (виконайте з ноутбука)
for p in 5432 6379 8000 80 443; do nc -zvw3 $DOMAIN $p; done        # 5432, 6379, 8000 мають відмовити
# 2. реєстрація і вхід
#    https://$DOMAIN/ у браузері, потім імпорт тендера за UA-ID
# 3. пам'ять і ліміти
docker stats --no-stream
# 4. своп і диск
free -h; df -h /
```

## 5. Оновлення

```bash
cd ~/CheckIT
# перед оновленням зробіть бекап (розділ 8)
git fetch --all --tags
git checkout <гілка-або-тег>        # для staging зазвичай dev, для prod тег версії
git pull --ff-only                  # лише якщо гілка
dc build
dc up -d                            # міграції Alembic виконуються при старті backend
dc ps && dc logs --tail=50 backend
docker builder prune -f && docker image prune -f      # прибрати кеш збірки
```
**Відкат:** `git checkout <попередній коміт або тег>`, `dc build`, `dc up -d`. Міграції автоматично назад не відкочуються: якщо оновлення змінило схему, спершу відновіть базу з бекапу, зробленого перед оновленням.

## 6. Логи

```bash
dc ps                                   # стан і healthcheck
dc logs -f --tail=100 backend           # слідкувати за backend
dc logs --tail=100 caddy db redis frontend
sudo journalctl -u ssh --since today    # спроби входу по SSH
```
Логи контейнерів ротуються автоматично (10 МБ × 5 файлів на сервіс).

## 7. Зупинка і запуск

```bash
dc stop             # зупинити, нічого не видаляючи
dc start            # запустити знову
dc down             # прибрати контейнери (томи з даними лишаються)
dc restart backend
```
Після перезавантаження сервера сервіси стартують самі (`restart: unless-stopped`).

## 8. Тимчасовий бекап до E7.5

```bash
mkdir -p ~/backups
dc exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > ~/backups/checkit-$(date +%F-%H%M).sql.gz
ls -lh ~/backups
```
Скопіюйте файл з сервера (`scp deploy@<IP>:backups/<файл> .`): бекап на тому самому диску не рятує від втрати сервера. Автоматичні бекапи у зовнішнє сховище: крок E7.5.

## 9. Чого не робити

- `docker compose down -v`, `docker volume prune`, `docker system prune --volumes`: знищують базу.
- Додавати `ports:` до `db`, `redis`, `backend`, `frontend` (обходить фаєрвол).
- Комітити `.env.staging`, копіювати локальний `.env` на сервер, використовувати той самий `SECRET_KEY` чи пароль бази, що й локально.
- Працювати під `root` або вмикати вхід за паролем по SSH.
- Лишати збірковий кеш: після кожної збірки `docker builder prune -f && docker image prune -f`, диск перевіряти через `df -h /` і `docker system df`.

## 10. Що потребує реального сервера (чекліст E0.6 «після купівлі VPS»)

- [ ] VPS Ubuntu 24.04 куплено, домен спрямовано на нього (розділ 3)
- [ ] Розділ 1 пройдено на чистій системі, SSH лише за ключем перевірено, `ufw` увімкнено, свопфайл є
- [ ] `check_sources.py` виконано першим ділом, абзац у `DIPLOMA_NOTES.md`
- [ ] `check_env_staging.py` дає OK, `SECRET_KEY` і пароль бази нові
- [ ] Перший деплой на тестовому ACME, потім справжній сертифікат, HTTPS працює
- [ ] Назовні відкриті лише 80 і 443 (перевірка `nc`)
- [ ] Імпорт тендера за UA-ID працює на сервері
- [ ] Цифри `docker stats`, `free -h`, час збірки записано в `DIPLOMA_NOTES.md`
