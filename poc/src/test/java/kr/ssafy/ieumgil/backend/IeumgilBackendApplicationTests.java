package kr.ssafy.ieumgil.backend;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;
import org.testcontainers.utility.MountableFile;

@Testcontainers
@SpringBootTest
class IeumgilBackendApplicationTests {

	@Container
	static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>(
			DockerImageName.parse("postgis/postgis:16-3.4").asCompatibleSubstituteFor("postgres"))
			.withCopyFileToContainer(
					MountableFile.forHostPath("../db/schema.sql"),
					"/docker-entrypoint-initdb.d/01_schema.sql"
			);

	@DynamicPropertySource
	static void overrideDataSource(DynamicPropertyRegistry registry) {
		registry.add("spring.datasource.url", postgres::getJdbcUrl);
		registry.add("spring.datasource.username", postgres::getUsername);
		registry.add("spring.datasource.password", postgres::getPassword);
	}

	@Test
	void contextLoads() {
		// ddl-auto=validate 가 실제 PostGIS 컨테이너 스키마와 엔티티 매핑을 검증한다.
		// 워크스트림 02 이후 Entity 클래스가 추가되면 이 테스트가 스키마 정합성 방어선이 된다.
	}
}
