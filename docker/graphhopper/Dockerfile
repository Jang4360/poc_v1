FROM maven:3.9.9-eclipse-temurin-21 AS plugin-build
WORKDIR /workspace
COPY graphhopper-plugin/pom.xml graphhopper-plugin/pom.xml
COPY graphhopper-plugin/src graphhopper-plugin/src
RUN mvn -q -f graphhopper-plugin/pom.xml -DskipTests package

FROM eclipse-temurin:21-jre
ARG GRAPHHOPPER_VERSION=9.1
WORKDIR /graphhopper

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL \
    -o /graphhopper/graphhopper-web.jar \
    "https://repo1.maven.org/maven2/com/graphhopper/graphhopper-web/${GRAPHHOPPER_VERSION}/graphhopper-web-${GRAPHHOPPER_VERSION}.jar"

COPY --from=plugin-build /workspace/graphhopper-plugin/target/ieum-graphhopper-plugin-0.1.0-SNAPSHOT.jar /graphhopper/plugins/ieum-graphhopper-plugin.jar
COPY graphhopper/config.yml /config/config.yml
COPY graphhopper/custom_models /config/custom_models
COPY graphhopper/data/gangseo.osm.pbf /data/gangseo.osm.pbf
COPY docker/graphhopper/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 8989 8990
ENTRYPOINT ["/entrypoint.sh"]
