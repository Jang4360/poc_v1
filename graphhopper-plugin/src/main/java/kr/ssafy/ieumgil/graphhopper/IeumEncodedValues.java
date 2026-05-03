package kr.ssafy.ieumgil.graphhopper;

import com.graphhopper.routing.ev.DecimalEncodedValue;
import com.graphhopper.routing.ev.DecimalEncodedValueImpl;
import com.graphhopper.routing.ev.EnumEncodedValue;

public final class IeumEncodedValues {
    public static final String WALK_ACCESS = "walk_access";
    public static final String AVG_SLOPE_PERCENT = "avg_slope_percent";
    public static final String WIDTH_METER = "width_meter";
    public static final String BRAILLE_BLOCK_STATE = "braille_block_state";
    public static final String AUDIO_SIGNAL_STATE = "audio_signal_state";
    public static final String SLOPE_STATE = "slope_state";
    public static final String WIDTH_STATE = "width_state";
    public static final String SURFACE_STATE = "surface_state";
    public static final String STAIRS_STATE = "stairs_state";
    public static final String SIGNAL_STATE = "signal_state";
    public static final String SEGMENT_TYPE = "segment_type";

    private IeumEncodedValues() {
    }

    public static EnumEncodedValue<AccessibilityState> walkAccess() {
        return new EnumEncodedValue<>(WALK_ACCESS, AccessibilityState.class);
    }

    public static DecimalEncodedValue avgSlopePercent() {
        return new DecimalEncodedValueImpl(AVG_SLOPE_PERCENT, 9, 0, 0.25, false, false, false);
    }

    public static DecimalEncodedValue widthMeter() {
        return new DecimalEncodedValueImpl(WIDTH_METER, 9, 0, 0.05, false, false, false);
    }

    public static EnumEncodedValue<AccessibilityState> brailleBlockState() {
        return new EnumEncodedValue<>(BRAILLE_BLOCK_STATE, AccessibilityState.class);
    }

    public static EnumEncodedValue<AccessibilityState> audioSignalState() {
        return new EnumEncodedValue<>(AUDIO_SIGNAL_STATE, AccessibilityState.class);
    }

    public static EnumEncodedValue<SlopeState> slopeState() {
        return new EnumEncodedValue<>(SLOPE_STATE, SlopeState.class);
    }

    public static EnumEncodedValue<WidthState> widthState() {
        return new EnumEncodedValue<>(WIDTH_STATE, WidthState.class);
    }

    public static EnumEncodedValue<SurfaceState> surfaceState() {
        return new EnumEncodedValue<>(SURFACE_STATE, SurfaceState.class);
    }

    public static EnumEncodedValue<AccessibilityState> stairsState() {
        return new EnumEncodedValue<>(STAIRS_STATE, AccessibilityState.class);
    }

    public static EnumEncodedValue<SignalState> signalState() {
        return new EnumEncodedValue<>(SIGNAL_STATE, SignalState.class);
    }

    public static EnumEncodedValue<SegmentType> segmentType() {
        return new EnumEncodedValue<>(SEGMENT_TYPE, SegmentType.class);
    }
}
