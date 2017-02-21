FROM debian:latest
RUN apt-get update && apt-get dist-upgrade -y
RUN apt-get install python ca-certificates -y
CMD ./app.py
ADD app.py .
