// TouchDesigner Log Dimensionless Jerk CHOP - wraps ew::motion::LogDimensionlessJerk (speed_profile_metrics.h)
// LDLJ, the smoothness of a speed or acceleration profile from its jerk.
// Input: 1 channel speed profile window (samples over time).
// Fewer than 10 samples (as PyEyesWeb): status WarmingUp ("k of 10 samples"), output 0.
// NaN / infinity in the input: InvalidInput.
// Output: 1 channel, one sample: log_dimensionless_jerk.
#include <cstring>
#include <string>
#include <vector>
#include "ew/features/motion/speed_profile_metrics.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;

namespace {
constexpr int kMinimumSamples = static_cast<int>(ew::motion::kMinimumSpeedProfileSamples);
}

class LogDimensionlessJerkCHOP : public EwChop {
public:
    explicit LogDimensionlessJerkCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("log_dimensionless_jerk")}; }

    void declareParameters(Params& p) override {
        p.page("Log Dimensionless Jerk");
        p.menu("Inputmode", "Input Mode", "velocity",
               {{"velocity", "Velocity / Speed"}, {"acceleration", "Acceleration Magnitude"}});
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

        ew::motion::LogDimensionlessJerk::Params p;
        p.samplingRate = input.sampleRate();
        p.inputMode = std::strcmp(in->getParString("Inputmode"), "acceleration") == 0
                          ? ew::motion::JerkInputMode::Acceleration
                          : ew::motion::JerkInputMode::Velocity;
        out->channels[0][0] = static_cast<float>(ew::motion::LogDimensionlessJerk(p).process(speed));
    }
};

EW_TD_CHOP(LogDimensionlessJerkCHOP, "Ewlogdimensionlessjerk", "EW L2 Log Dimensionless Jerk", 1, 1)
