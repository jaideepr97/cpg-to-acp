FROM registry.access.redhat.com/ubi9/openjdk-17:latest AS build

USER root
WORKDIR /build

COPY pom.xml .
RUN mvn dependency:go-offline -B

COPY src/ src/
RUN mvn package -DskipTests -B

FROM registry.access.redhat.com/ubi9/openjdk-17-runtime:latest

USER root

WORKDIR /app

COPY --from=build /build/target/quarkus-app/ /app/

RUN chmod -R g=u /app

USER 185

EXPOSE 8081

ENV JAVA_OPTS_APPEND="-Dquarkus.http.host=0.0.0.0"

ENTRYPOINT ["java", "-jar", "/app/quarkus-run.jar"]
