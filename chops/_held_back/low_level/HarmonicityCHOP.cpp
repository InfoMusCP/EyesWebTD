// TouchDesigner Harmonicity CHOP - wraps ew::motion::Harmonicity (speed_profile_metrics.h)
// Harmonicity of a speed profile, in [0, 1].
// Input: 1 channel speed profile window (samples over time).
// Fewer than 10 samples (as PyEyesWeb): status WarmingUp ("k of 10 samples"), output 0.
// NaN / infinity in the input: InvalidInput.
// Output: 1 channel, one sample: harmonicity.
#include <string>
#include <vector>
#include "ew/features/motion/speed_profile_metrics.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;

namespace {
constexpr int kMinimumSamples = static_cast<int>(ew::motion::kMinimumSpeedProfileSamples);
}

class HarmonicityCHOP : public EwChop {
public:
    explicit HarmonicityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("harmonicity")}; }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        require(input.channels() >= 1, "Requires at least 1 input channel (speed profile)");
        if (input.samples() < kMinimumSamples) {
            setStatus(Status::WarmingUp, std::to_string(input.samples()) + " of " + std::to_string(kMinimumSamples) + " samples");
            return;
        }

        std::vector<double> speed(input.samples());
        for (int s = 0; s < input.samples(); ++s) speed[s] = input.at(0, s);

        ew::motion::Harmonicity::Params p;
        p.samplingRate = input.sampleRate();
        out->channels[0][0] = static_cast<float>(ew::motion::Harmonicity(p).process(speed));
    }
};

EW_TD_CHOP(HarmonicityCHOP, "Ewharmonicity", "EW L2 Harmonicity", 1, 1)
