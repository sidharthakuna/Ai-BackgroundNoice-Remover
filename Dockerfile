FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y python3 python3-pip

RUN pip3 install noisereduce scipy soundfile numpy --break-system-packages

WORKDIR /app

COPY . .

RUN chmod +x mvnw && ./mvnw package -DskipTests

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "target/AI-Backgroound-Noice-Remover-0.0.1-SNAPSHOT.jar"]