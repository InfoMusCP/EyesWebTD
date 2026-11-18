// TouchDesigner Binary Pulses Regularity CHOP - wraps ew::base::BinaryPulsesRegularity.
// Input: 1 channel, a pulse train (a non-zero sample is a pulse) over the samples of the window: the input is the window
// (a Trail CHOP of the pulses, a File In). Output: 2 channels x 1 sample (is_regular, pulse_count). The moment the movement
// becomes regular is the rising edge of is_regular: a Logic CHOP (Convert Input: off to on) computes it after the operator.
// Fewer than 3 samples: WARMING_UP; a NaN or infinity: INVALID_INPUT. Nothing is kept between cooks.
#include <vector>
#include "ew/common/time_series.h"
#include "ew/features/base/binary_pulses_regularity.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::base::BinaryPulsesRegularity;

class BinaryPulsesRegularityCHOP : public EwChop {
public:
    explicit BinaryPulsesRegularityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        return {Output::scalar("is_regular"), Output::scalar("pulse_count")};
    }

    void declareParameters(Params& p) override {
        p.page("Pulses");
        p.integer("Threshold", "Threshold (samples, spread below it)", 1, Range::atLeast(1, 20));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        require(input.channels() == 1, "Requires 1 input channel");
        requireFinite(input);
        const int n = input.samples();
        if (n < 3) return windowTooShort(n, 3);

        BinaryPulsesRegularity::Params p;
        p.threshold = in->getParInt("Threshold");
        std::vector<double> window(static_cast<size_t>(n));
        for (int s = 0; s < n; ++s) window[static_cast<size_t>(s)] = input.at(0, s);
        ew::TimeSeriesView view;
        view.data = window.data();
        view.channels = 1;
        view.samples = static_cast<size_t>(n);
        view.samplingRate = input.sampleRate();
        const BinaryPulsesRegularity::Output result = BinaryPulsesRegularity(p).process(view);
        out->channels[0][0] = result.regular ? 1.f : 0.f;
        out->channels[1][0] = static_cast<float>(result.pulseCount);
    }
};

EW_TD_CHOP(BinaryPulsesRegularityCHOP, "Ewbinarypulsesregularity", "EW AP Binary Pulses Regularity", 1, 1)
