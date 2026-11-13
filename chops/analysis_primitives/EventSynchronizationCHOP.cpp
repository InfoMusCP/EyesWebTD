// TouchDesigner Event Synchronization CHOP - wraps ew::sync::EventSynchronization
// Quian Quiroga event synchronization of two event trains.
// Input: 2 channels (the trains x and y; a non-zero sample is an event) across the samples of the buffer.
// Output: 2 channels, 1 sample: synchronization (Q) and delay (q, delay / leadership index).
// Buffer with state: the events left unmatched by one cook are matched with those of the next ones, unless Reset Every
// Buffer is on; Reset forgets them.
#include <vector>
#include "ew/common/time_series.h"
#include "ew/features/sync/event_synchronization.h"
#include "ew_td/plugin.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::TimeSeriesView;
using ew::sync::EventSynchronization;

class EventSynchronizationCHOP : public EwBufferChop {
public:
    explicit EventSynchronizationCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("synchronization"), Output::scalar("delay")}; }

    void declareParameters(Params& p) override {
        p.page("Event Sync");
        p.integer("Maxlag", "Max Lag (samples)", 5, Range::atLeast(1, 50));
        p.toggle("Reseteverybuffer", "Reset Every Buffer", true);
    }

    void dropState() override { feature_.drop(); }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        require(input.channels() >= 2, "Requires at least 2 channels (event trains x and y)");

        EventSynchronization::Params p;
        p.maxLag = in->getParInt("Maxlag");
        p.resetEveryBuffer = in->getParInt("Reseteverybuffer") != 0;
        EventSynchronization& feature = feature_.get(p);

        const int n = input.samples();
        std::vector<double> sx(n), sy(n);
        for (int s = 0; s < n; ++s) {
            sx[s] = input.at(0, s);
            sy[s] = input.at(1, s);
        }
        const TimeSeriesView tsx{sx.data(), 1, static_cast<size_t>(n), input.sampleRate()};
        const TimeSeriesView tsy{sy.data(), 1, static_cast<size_t>(n), input.sampleRate()};

        const EventSynchronization::Result result = feature.process(tsx, tsy);
        out->channels[0][0] = static_cast<float>(result.Q);
        out->channels[1][0] = static_cast<float>(result.q);
    }

private:
    FeatureSlot<EventSynchronization> feature_;
};

EW_TD_CHOP(EventSynchronizationCHOP, "Eweventsynchronization", "EW AP Event Synchronization", 1, 1)
