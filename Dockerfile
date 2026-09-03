# Один образ на два продукта: бот и лендинги.
#
# На Render тариф привязан к сервису, поэтому два сервиса — это два счёта, и
# на бесплатном тарифе оба засыпают. Один платный сервис закрывает и то и
# другое, но только если сервис действительно один: отсюда сборка в две
# стадии — Node собирает статику, Python её раздаёт вместе с вебхуком.
#
# Node в финальный образ не попадает: там остаётся только папка `dist`.
# На 512 МБ бесплатного тарифа это принципиально.

# --- стадия 1: сборка лендингов ---------------------------------------------
FROM node:22.12-slim AS site

WORKDIR /site

# Зависимости отдельным слоем: пока package.json не менялся, повторная
# сборка не тянет npm заново.
#
# Здесь `npm install`, а не `npm ci`, хотя ci строже и воспроизводимее.
# Причина простая: на сервисе лендинга сборка много месяцев идёт командой
# `npm install && npm run build` и не падала ни разу, а первая же сборка с
# `npm ci` упала с EUSAGE. Разбираться, чем именно не устроил lock-файл,
# дешевле не в проде — а пока берём то, что заведомо работает.
COPY site/package.json site/package-lock.json ./
RUN npm install --no-audit --no-fund

COPY site/ ./
# Собирает Astro и рядом кладёт .br и .gz — их отдаёт utils/site.py.
RUN npm run build

# --- стадия 2: бот, он же веб-сервер ----------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Модель распознавания кладётся в образ на сборке.
#
# Диск на Render эфемерный: не запеки её здесь — и она будет скачиваться заново
# после каждого деплоя, а первая заметка после выката будет ждать эту закачку.
#
# Значение должно совпадать с NOTES_WHISPER_MODEL в окружении. Разойдутся —
# сервис не сломается, но модель уедет качаться в рантайме, то есть ровно то,
# от чего эта строка и защищает.
ARG NOTES_WHISPER_MODEL=base
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${NOTES_WHISPER_MODEL}', device='cpu', compute_type='int8')"

COPY . .

# Исходники сайта в образе не нужны — нужна только сборка. Кладём её туда, где
# её ищет utils/site.py.
RUN rm -rf /app/site
COPY --from=site /site/dist /app/site/dist

CMD ["python", "main.py"]
