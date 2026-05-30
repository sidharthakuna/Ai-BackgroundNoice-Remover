FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y python3 python3-pip

RUN pip3 install noisereduce scipy soundfile numpy --break-system-packages

WORKDIR /app

COPY target/*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]