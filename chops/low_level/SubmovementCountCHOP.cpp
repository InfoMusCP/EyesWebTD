// TouchDesigner Submovement Count CHOP - wraps ew::motion::SubmovementCount (speed_profile_metrics.h)
// Number of prominent speed peaks of a speed profile.
// Input: 1 channel speed profile window (samples over time).
// Fewer than 10 samples (as PyEyesWeb): status WarmingUp ("k of 10 samples"), output 0.
// NaN / infinity in the input: InvalidInput.
// Output: 1 channel, one sample: submovement_count.
#include <string>
#include <vector>
#include "ew/features/motion/speed_profile_metrics.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;

namespace {
constexpr int kMinimumSamples = static_cast<int>(ew::motion::kMinimumSpeedProfileSamples);
}

class SubmovementCountCHOP : public EwChop {
public:
    explicit SubmovementCountCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("submovement_count")}; }

    void declareParameters(Params& p) override {
        p.page("Submovement Count");
        p.number("Prominencefactor", "Prominence Factor", 0.1, Range::atLeast(0.0, 0.5));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        require(input.channels() >= 1, "Requires at least 1 input channel (speed profile)");
        if (input.samples() < kMinimumSamples) {
            windowTooShort(input.samples(), kMinimumSamples);
            return;
        }

        std::vector<double> speed(input.samples());
        for (int s = 0; s < input.samples(); ++s) speed[s] = input.at(0, s);

        ew::motion::SubmovementCount::Params p;
        p.samplingRate = input.sampleRate();
        p.prominenceFactor = in->getParDouble("Prominencefactor");
        out->channels[0][0] = static_cast<float>(ew::motion::SubmovementCount(p).process(speed));
    }
};

EW_TD_CHOP(SubmovementCountCHOP, "Ewsubmovementcount", "EW L2 Submovement Count", 1, 1)
