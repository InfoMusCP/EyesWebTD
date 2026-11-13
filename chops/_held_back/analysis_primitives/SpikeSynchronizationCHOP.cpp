// TouchDesigner Spike Synchronization CHOP - wraps ew::sync::SpikeES
// Multivariate SPIKE-synchronization across spike trains.
// Input: N channels, one spike train each (binary mode: a sample > 0 is a spike (+1), anything else -1; timings mode: spike times > 0 and increasing,
// otherwise INVALID_INPUT).
// Output: 2 channels, 1 sample: degree (S in [0, 1]) and distance (1 - S).
// Frame operator: the trains are the CHOP content, nothing is kept between cooks.
#include <cstring>
#include <vector>
#include "ew/common/time_series.h"
#include "ew/features/sync/spike_sync.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::TimeSeriesView;
using ew::sync::SpikeES;

class SpikeSynchronizationCHOP : public EwChop {
public:
    explicit SpikeSynchronizationCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("degree"), Output::scalar("distance")}; }

    void declareParameters(Params& p) override {
        p.page("SPIKE Sync");
        p.menu("Mode", "Execution Mode", "binary",
               {{"binary", "Binary (-1/+1 Spikes)"}, {"timings", "Timings (Spike Times > 0)"}});
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        const int nTrains = input.channels();
        require(nTrains >= 2, "Requires at least 2 input channels (spike trains)");

        SpikeES::Params p;
        p.numberOfInputs = nTrains;
        p.mode = std::strcmp(in->getParString("Mode"), "timings") == 0 ? SpikeES::Mode::Timings : SpikeES::Mode::Binary;

        const int n = input.samples();
        std::vector<std::vector<double>> trainBuf(nTrains, std::vector<double>(n));
        std::vector<TimeSeriesView> views(nTrains);
        for (int i = 0; i < nTrains; ++i) {
            for (int s = 0; s < n; ++s) {
                const double v = input.at(i, s);
                trainBuf[i][s] = p.mode == SpikeES::Mode::Binary ? (v > 0 ? 1.0 : -1.0) : v;
                if (p.mode == SpikeES::Mode::Timings) {
                    require(!(v <= 0), "spike times must be > 0");
                    require(s == 0 || !(v <= trainBuf[i][s - 1]), "spike times must increase within each train");
                }
            }
            views[i].data = trainBuf[i].data();
            views[i].channels = 1;
            views[i].samples = n;
            views[i].samplingRate = input.sampleRate();
        }

        const SpikeES feature(p);
        const SpikeES::Result result = feature.process(views);
        out->channels[0][0] = static_cast<float>(result.degree);
        out->channels[1][0] = static_cast<float>(result.distance);
    }
};

EW_TD_CHOP(SpikeSynchronizationCHOP, "Ewspikesynchronization", "EW AP Spike Synchronization", 1, 1)
