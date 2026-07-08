
FROM python:3.13-slim

# host docker.internal -> localhost
# curl -X POST -d '{"message": "Hello, world!"}' http://host.docker.internal:8080/api/chats/
# Invoke-RestMethod -Method POST -Uri "http://host.docker.internal:8080/api/chats/" -ContentType "application/json" -Body '{"message": "Hello, world!"}'
RUN apt-get update && apt-get install -y curl

RUN python -m venv /opt/venv/
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app 

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY ./src .

CMD ["python", "-m", "http.server", "8000"]