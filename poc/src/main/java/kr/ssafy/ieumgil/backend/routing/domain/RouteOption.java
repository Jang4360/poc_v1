package kr.ssafy.ieumgil.backend.routing.domain;

import com.fasterxml.jackson.annotation.JsonCreator;

import java.util.Locale;

public enum RouteOption {
    SAFE,
    SHORTEST,
    PUBLIC_TRANSPORT;

    @JsonCreator
    public static RouteOption from(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String normalized = value.trim().toUpperCase(Locale.ROOT);
        return switch (normalized) {
            case "SAFE", "SAFETY", "안전", "안전길" -> SAFE;
            case "SHORTEST", "FAST", "FASTEST", "빠른길", "최단", "최단거리" -> SHORTEST;
            case "PUBLIC_TRANSPORT", "TRANSIT", "대중교통" -> PUBLIC_TRANSPORT;
            default -> throw new IllegalArgumentException("Unsupported routeOption: " + value);
        };
    }
}
