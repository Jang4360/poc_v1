package kr.ssafy.ieumgil.backend.routing.service;

import kr.ssafy.ieumgil.backend.routing.domain.DisabilityType;
import kr.ssafy.ieumgil.backend.routing.domain.RouteOption;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class RoutingProfileResolverTest {
    private final RoutingProfileResolver resolver = new RoutingProfileResolver();

    @Test
    void mapsPublicRequestEnumsToInternalGraphHopperProfiles() {
        assertThat(resolver.resolve(DisabilityType.VISUAL, RouteOption.SAFE)).isEqualTo("visual_safe");
        assertThat(resolver.resolve(DisabilityType.VISUAL, RouteOption.SHORTEST)).isEqualTo("visual_fast");
        assertThat(resolver.resolve(DisabilityType.MOBILITY, RouteOption.SAFE)).isEqualTo("wheelchair_manual_safe");
        assertThat(resolver.resolve(DisabilityType.MOBILITY, RouteOption.SHORTEST)).isEqualTo("wheelchair_manual_fast");
    }

    @Test
    void rejectsUnsupportedTransitProfileForThisSlice() {
        assertThatThrownBy(() -> resolver.resolve(DisabilityType.MOBILITY, RouteOption.PUBLIC_TRANSPORT))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
