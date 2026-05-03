package kr.ssafy.ieumgil.graphhopper;

import com.graphhopper.reader.ReaderWay;
import com.graphhopper.routing.ev.ArrayEdgeIntAccess;
import com.graphhopper.routing.ev.DecimalEncodedValue;
import com.graphhopper.routing.ev.EnumEncodedValue;
import com.graphhopper.routing.ev.ImportUnit;
import com.graphhopper.routing.ev.EncodedValue;
import com.graphhopper.routing.util.EncodingManager;
import com.graphhopper.routing.util.parsers.TagParser;
import com.graphhopper.util.PMap;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class IeumImportRegistryTest {
    @Test
    void createsEnumImportUnitAndParsesOsmTag() {
        IeumImportRegistry registry = new IeumImportRegistry();
        ImportUnit unit = registry.createImportUnit(IeumEncodedValues.SLOPE_STATE);
        EncodedValue encodedValue = unit.getCreateEncodedValue().apply(new PMap());

        EncodingManager encodingManager = EncodingManager.start().add(encodedValue).build();
        TagParser parser = unit.getCreateTagParser().apply(encodingManager, new PMap());
        ReaderWay way = new ReaderWay(1);
        way.setTag("ieum:slope_state", "STEEP");

        ArrayEdgeIntAccess edgeIntAccess = new ArrayEdgeIntAccess(8);
        parser.handleWayTags(0, edgeIntAccess, way, null);

        EnumEncodedValue<SlopeState> slopeState = encodingManager.getEnumEncodedValue(IeumEncodedValues.SLOPE_STATE, SlopeState.class);
        assertEquals(SlopeState.STEEP, slopeState.getEnum(false, 0, edgeIntAccess));
    }

    @Test
    void invalidEnumValuesFallbackToUnknown() {
        EnumEncodedValue<SignalState> signalState = IeumEncodedValues.signalState();
        EncodingManager encodingManager = EncodingManager.start().add(signalState).build();
        TagParser parser = new IeumEnumTagParser<>(
                "ieum:signal_state",
                encodingManager.getEnumEncodedValue(IeumEncodedValues.SIGNAL_STATE, SignalState.class),
                SignalState.class,
                SignalState.UNKNOWN
        );
        ReaderWay way = new ReaderWay(2);
        way.setTag("ieum:signal_state", "BROKEN_VALUE");

        ArrayEdgeIntAccess edgeIntAccess = new ArrayEdgeIntAccess(8);
        parser.handleWayTags(0, edgeIntAccess, way, null);

        assertEquals(SignalState.UNKNOWN, signalState.getEnum(false, 0, edgeIntAccess));
    }

    @Test
    void decimalUnknownValuesFallbackToZero() {
        DecimalEncodedValue widthMeter = IeumEncodedValues.widthMeter();
        EncodingManager.start().add(widthMeter).build();
        TagParser parser = new IeumDecimalTagParser("ieum:width_meter", widthMeter, 0.0);
        ReaderWay way = new ReaderWay(3);
        way.setTag("ieum:width_meter", "UNKNOWN");

        ArrayEdgeIntAccess edgeIntAccess = new ArrayEdgeIntAccess(8);
        parser.handleWayTags(0, edgeIntAccess, way, null);

        assertEquals(0.0, widthMeter.getDecimal(false, 0, edgeIntAccess), 0.001);
    }

    @Test
    void delegatesBuiltInImportUnitsToGraphHopperRegistry() {
        IeumImportRegistry registry = new IeumImportRegistry();
        assertNotNull(registry.createImportUnit("foot_access"));
    }
}
