// TouchDesigner Nonlinear Interdependence CHOP - wraps ew::sync::EventSynchronizationInterdependence
// Arnhold nonlinear interdependence of two series, from the nearest neighbours of their delay vectors.
// Input: 2 channels (the series x and y) across the samples of the window.
// Output: 3 channels, 1 sample: first_to_second_interdependence S(X|Y), second_to_first_interdependence S(Y|X),
// threshold.
// Frame operator: the window is the CHOP content, nothing is kept between cooks.
#include <vector>
#include "ew/common/time_series.h"
#include "ew/features/sync/interdependence.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::TimeSeriesView;
using ew::sync::EventSynchronizationInterdependence;

class NonlinearInterdependenceCHOP : public EwChop {
public:
    explicit NonlinearInterdependenceCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        return {Output::scalar("first_to_second_interdependence"), Output::scalar("second_to_first_interdependence"),
                Output::scalar("threshold")};
    }

    void declareParameters(Params& p) override {
        p.page("Interdependence");
        p.integer("Embeddingdim", "Delay Embedding Dim", 2, Range::atLeast(1, 10));
        p.integer("Neighbours", "Nearest Neighbours", 5, Range::atLeast(1, 50));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        require(input.channels() >= 2, "Requires at least 2 channels (x and y)");

        EventSynchronizationInterdependence::Params p;
        p.embeddingDimension = in->getParInt("Embeddingdim");
        p.neighbours = in->getParInt("Neighbours");

        const int n = input.samples();
        std::vector<double> sx(n), sy(n);
        for (int s = 0; s < n; ++s) {
            sx[s] = input.at(0, s);
            sy[s] = input.at(1, s);
        }
        const TimeSeriesView tx{sx.data(), 1, static_cast<size_t>(n), input.sampleRate()};
        const TimeSeriesView ty{sy.data(), 1, static_cast<size_t>(n), input.sampleRate()};

        const EventSynchronizationInterdependence feature(p);
        const EventSynchronizationInterdependence::Result result = feature.process(tx, ty);
        out->channels[0][0] = static_cast<float>(result.xy);
        out->channels[1][0] = static_cast<float>(result.yx);
        out->channels[2][0] = static_cast<float>(result.threshold);
    }
};

EW_TD_CHOP(NonlinearInterdependenceCHOP, "Ewnonlinearinterdependence", "EW AP Nonlinear Interdependence", 1, 1)
