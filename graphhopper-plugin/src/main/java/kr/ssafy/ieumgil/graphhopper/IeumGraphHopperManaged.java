package kr.ssafy.ieumgil.graphhopper;

import com.graphhopper.GraphHopper;
import com.graphhopper.GraphHopperConfig;
import io.dropwizard.lifecycle.Managed;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class IeumGraphHopperManaged implements Managed {
    private static final Logger LOGGER = LoggerFactory.getLogger(IeumGraphHopperManaged.class);

    private final GraphHopper graphHopper;
    private boolean started;

    public IeumGraphHopperManaged(GraphHopperConfig config) {
        this.graphHopper = new GraphHopper()
                .setImportRegistry(new IeumImportRegistry())
                .init(config);
    }

    @Override
    public void start() {
        if (started) {
            return;
        }
        graphHopper.importOrLoad();
        started = true;
        LOGGER.info("GraphHopper started with Ieum custom encoded values: {}", graphHopper.getEncodingManager());
    }

    public GraphHopper getGraphHopper() {
        return graphHopper;
    }

    @Override
    public void stop() {
        graphHopper.close();
    }
}
