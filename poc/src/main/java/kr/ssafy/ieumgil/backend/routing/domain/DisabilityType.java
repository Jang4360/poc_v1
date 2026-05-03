package kr.ssafy.ieumgil.backend.routing.domain;

import com.fasterxml.jackson.annotation.JsonCreator;

import java.util.Locale;

public enum DisabilityType {
    VISUAL,
    MOBILITY;

    @JsonCreator
    public static DisabilityType from(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String normalized = value.trim().toUpperCase(Locale.ROOT);
        return switch (normalized) {
            case "VISUAL", "BLIND", "시각장애", "시각장애인" -> VISUAL;
            case "MOBILITY", "WHEELCHAIR", "WHEELCHAIR_MANUAL", "MANUAL_WHEELCHAIR", "보행약자", "수동휠체어" -> MOBILITY;
            default -> throw new IllegalArgumentException("Unsupported disabilityType: " + value);
        };
    }
}
