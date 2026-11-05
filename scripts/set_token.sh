#!/bin/zsh
# Записывает токен бота в .env. Токен вводится скрыто и не попадает в историю команд и на экран.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { umask 077; cp .env.example .env; }

read -rs "token?Вставьте токен от @BotFather и нажмите Enter: "
echo
if [[ ! "$token" =~ '^[0-9]+:[A-Za-z0-9_-]{30,}$' ]]; then
  echo "Не похоже на токен — ничего не изменено." >&2
  exit 1
fi

if grep -q '^BOT_TOKEN=' .env; then
  sed -i '' "s|^BOT_TOKEN=.*|BOT_TOKEN=$token|" .env
else
  print "BOT_TOKEN=$token" >> .env
fi
chmod 600 .env
unset token
echo "Токен записан в .env. Запуск: .venv/bin/python -m booking_bot"
