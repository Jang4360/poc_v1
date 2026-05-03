package kr.ssafy.ieumgil.graphhopper;

import com.graphhopper.routing.ev.DefaultImportRegistry;
import com.graphhopper.routing.ev.DecimalEncodedValue;
import com.graphhopper.routing.ev.EncodedValueLookup;
import com.graphhopper.routing.ev.EnumEncodedValue;
import com.graphhopper.routing.ev.ImportRegistry;
import com.graphhopper.routing.ev.ImportUnit;
import com.graphhopper.routing.util.parsers.TagParser;
import com.graphhopper.util.PMap;

import java.util.function.BiFunction;
import java.util.function.Function;

public final class IeumImportRegistry implements ImportRegistry {
    private final ImportRegistry delegate = new DefaultImportRegistry();

    @Override
    public ImportUnit createImportUnit(String name) {
        return switch (name) {
            case IeumEncodedValues.WALK_ACCESS -> enumUnit(
                    name,
                    pMap -> IeumEncodedValues.walkAccess(),
                    (lookup, pMap) -> enumParser("ieum:walk_access", lookup, name, AccessibilityState.class, AccessibilityState.UNKNOWN)
            );
            case IeumEncodedValues.AVG_SLOPE_PERCENT -> decimalUnit(
                    name,
                    pMap -> IeumEncodedValues.avgSlopePercent(),
                    (lookup, pMap) -> new IeumDecimalTagParser("ieum:avg_slope_percent", lookup.getDecimalEncodedValue(name), 0.0)
            );
            case IeumEncodedValues.WIDTH_METER -> decimalUnit(
                    name,
                    pMap -> IeumEncodedValues.widthMeter(),
                    (lookup, pMap) -> new IeumDecimalTagParser("ieum:width_meter", lookup.getDecimalEncodedValue(name), 0.0)
            );
            case IeumEncodedValues.BRAILLE_BLOCK_STATE -> enumUnit(
                    name,
                    pMap -> IeumEncodedValues.brailleBlockState(),
                    (lookup, pMap) -> enumParser("ieum:braille_block_state", lookup, name, AccessibilityState.class, AccessibilityState.UNKNOWN)
            );
            case IeumEncodedValues.AUDIO_SIGNAL_STATE -> enumUnit(
                    name,
                    pMap -> IeumEncodedValues.audioSignalState(),
                    (lookup, pMap) -> enumParser("ieum:audio_signal_state", lookup, name, AccessibilityState.class, AccessibilityState.UNKNOWN)
            );
            case IeumEncodedValues.SLOPE_STATE -> enumUnit(
                    name,
                    pMap -> IeumEncodedValues.slopeState(),
                    (lookup, pMap) -> enumParser("ieum:slope_state", lookup, name, SlopeState.class, SlopeState.UNKNOWN)
            );
            case IeumEncodedValues.WIDTH_STATE -> enumUnit(
                    name,
                    pMap -> IeumEncodedValues.widthState(),
                    (lookup, pMap) -> enumParser("ieum:width_state", lookup, name, WidthState.class, WidthState.UNKNOWN)
            );
            case IeumEncodedValues.SURFACE_STATE -> enumUnit(
                    name,
                    pMap -> IeumEncodedValues.surfaceState(),
                    (lookup, pMap) -> enumParser("ieum:surface_state", lookup, name, SurfaceState.class, SurfaceState.UNKNOWN)
            );
            case IeumEncodedValues.STAIRS_STATE -> enumUnit(
                    name,
                    pMap -> IeumEncodedValues.stairsState(),
                    (lookup, pMap) -> enumParser("ieum:stairs_state", lookup, name, AccessibilityState.class, AccessibilityState.UNKNOWN)
            );
            case IeumEncodedValues.SIGNAL_STATE -> enumUnit(
                    name,
                    pMap -> IeumEncodedValues.signalState(),
                    (lookup, pMap) -> enumParser("ieum:signal_state", lookup, name, SignalState.class, SignalState.UNKNOWN)
            );
            case IeumEncodedValues.SEGMENT_TYPE -> enumUnit(
                    name,
                    pMap -> IeumEncodedValues.segmentType(),
                    (lookup, pMap) -> enumParser("ieum:segment_type", lookup, name, SegmentType.class, SegmentType.UNKNOWN)
            );
            default -> delegate.createImportUnit(name);
        };
    }

    private static ImportUnit decimalUnit(
            String name,
            Function<PMap, DecimalEncodedValue> createEncodedValue,
            BiFunction<EncodedValueLookup, PMap, TagParser> createTagParser
    ) {
        return ImportUnit.create(name, createEncodedValue::apply, createTagParser::apply);
    }

    private static <E extends Enum<E>> ImportUnit enumUnit(
            String name,
            Function<PMap, EnumEncodedValue<E>> createEncodedValue,
            BiFunction<EncodedValueLookup, PMap, TagParser> createTagParser
    ) {
        return ImportUnit.create(name, createEncodedValue::apply, createTagParser::apply);
    }

    private static <E extends Enum<E>> TagParser enumParser(
            String osmTag,
            EncodedValueLookup lookup,
            String name,
            Class<E> enumClass,
            E fallback
    ) {
        return new IeumEnumTagParser<>(osmTag, lookup.getEnumEncodedValue(name, enumClass), enumClass, fallback);
    }
}
