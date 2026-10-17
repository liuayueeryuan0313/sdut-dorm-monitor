FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    TZ=Asia/Shanghai
WORKDIR /app

COPY aes_tool.py sdut_login.py sdut_ssws.py export_ssws.py sync_qqbot.py get_group_openid.py sdut_electricity.py webui.py notifications.py reminders.py ./
COPY web/ ./web/
RUN mkdir -p /app/data

EXPOSE 8787
STOPSIGNAL SIGTERM
CMD ["python", "webui.py", "--host", "0.0.0.0"]
