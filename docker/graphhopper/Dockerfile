FROM eclipse-temurin:21-jre
WORKDIR /graphhopper
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8989
ENTRYPOINT ["/entrypoint.sh"]
