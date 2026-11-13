// TouchDesigner Event Synchronization MECS CHOP - wraps ew::sync::EventSynchronizationMECS
// Multi Event Class Synchronization across N event trains with C event classes.
// Input: N * C channels (series0_c0, series0_c1, ..., series1_c0, ...) across the samples of the buffer.
// Output: 2 * C channels, 1 sample: synchronization_0..C-1, then events_0..C-1.
// Buffer with state: the core accumulates the events of the buffers it has seen; Reset forgets them.
#include <algorithm>
#include <cstring>
#include <vector>
#include "ew/common/time_series.h"
#include "ew/features/sync/event_synchronization_mecs.h"
#include "ew_td/plugin.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::TimeSeriesView;
using ew::sync::EventSynchronizationMECS;

class EventSynchronizationMECSCHOP : public EwBufferChop {
public:
    explicit EventSynchronizationMECSCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        const int classes = std::max(1, in->getParInt("Numberofeventclasses"));
        return {Output::indexed("synchronization", classes), Output::indexed("events", classes)};
    }

    void declareParameters(Params& p) override {
        p.page("MECS");
        p.integer("Numberofinputs", "Number of Inputs", 2, Range::atLeast(2, 16));
        p.integer("Numberofeventclasses", "Number of Event Classes", 2, Range::atLeast(1, 16));
        p.integer("Maxlag", "Max Lag (samples)", 10, Range::atLeast(1, 100));
        p.menu("Kernel", "Kernel Function", "linear",
               {{"uniform", "Uniform"}, {"linear", "Linear"}, {"gaussian", "Gaussian"}});
        p.toggle("Customgaussian", "Custom Gaussian (sigma, mean)", false);
        p.number("Gaussiansigma", "Gaussian Sigma (samples)", 10.0, Range::atLeast(0.0001, 100.0));
        p.number("Gaussianmean", "Gaussian Mean (samples)", 3.3333, Range::atLeast(0.0, 100.0));
    }

    void dropState() override { feature_.drop(); }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        const int numSeries = std::max(2, in->getParInt("Numberofinputs"));
        const int numClasses = std::max(1, in->getParInt("Numberofeventclasses"));
        require(input.channels() >= numSeries * numClasses, "Input requires NumSeries * Classes channels");

        EventSynchronizationMECS::Params p;
        p.numberOfInputs = numSeries;
        p.numberOfEventClasses = numClasses;
        p.maxLag = std::max(1, in->getParInt("Maxlag"));
        const char* kernel = in->getParString("Kernel");
        if (std::strcmp(kernel, "linear") == 0) p.kernel = EventSynchronizationMECS::Kernel::Linear;
        else if (std::strcmp(kernel, "gaussian") == 0) p.kernel = EventSynchronizationMECS::Kernel::Gaussian;
        else p.kernel = EventSynchronizationMECS::Kernel::Uniform;
        if (in->getParInt("Customgaussian") != 0) {  // otherwise the defaults of the core: sigma = Max Lag, mean = Max Lag / 3
            p.gaussianSigma = in->getParDouble("Gaussiansigma");
            p.gaussianMean = in->getParDouble("Gaussianmean");
        }
        EventSynchronizationMECS& feature = feature_.get(p);

        const int n = input.samples();
        std::vector<std::vector<double>> seriesBuf(numSeries, std::vector<double>(static_cast<size_t>(numClasses) * n));
        std::vector<TimeSeriesView> views(numSeries);
        for (int s = 0; s < numSeries; ++s) {
            for (int c = 0; c < numClasses; ++c)
                for (int t = 0; t < n; ++t) seriesBuf[s][static_cast<size_t>(c) * n + t] = input.at(s * numClasses + c, t);
            views[s].data = seriesBuf[s].data();
            views[s].channels = numClasses;
            views[s].samples = n;
            views[s].samplingRate = input.sampleRate();
        }

        const EventSynchronizationMECS::Result result = feature.process(views, 0);
        for (int c = 0; c < numClasses; ++c) {
            out->channels[c][0] = static_cast<float>(result.sync(0, c));
            out->channels[numClasses + c][0] = static_cast<float>(result.events(0, c));
        }
    }

private:
    FeatureSlot<EventSynchronizationMECS> feature_;
};

EW_TD_CHOP(EventSynchronizationMECSCHOP, "Eweventsynchronizationmecs", "EW AP Event Synchronization MECS", 1, 1)
