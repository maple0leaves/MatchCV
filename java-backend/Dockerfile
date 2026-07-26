FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /app

COPY pom.xml settings.xml ./
RUN mvn -s settings.xml -B -Dmaven.wagon.http.connectionTimeout=20000 -Dmaven.wagon.http.readTimeout=20000 dependency:go-offline

COPY src ./src
RUN mvn -s settings.xml -B -Dmaven.wagon.http.connectionTimeout=20000 -Dmaven.wagon.http.readTimeout=20000 package

FROM eclipse-temurin:17.0.13_11-jre-jammy
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app/target/*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]
