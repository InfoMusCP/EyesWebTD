// TouchDesigner Spectral Arc Length CHOP - wraps ew::motion::SpectralArcLength (speed_profile_metrics.h)
// SPARC, the smoothness of the amplitude spectrum of a speed profile.
// Input: 1 channel speed profile window (samples over time).
// Fewer than 10 samples (as PyEyesWeb): status WarmingUp ("k of 10 samples"), output 0.
// NaN / infinity in the input, or a profile with a NaN result (all zeros): InvalidInput.
// Output: 1 channel, one sample: spectral_arc_length.
#include <cmath>
#include <string>
#include <vector>
#include "ew/features/motion/speed_profile_metrics.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;

namespace {
constexpr int kMinimumSamples = static_cast<int>(ew::motion::kMinimumSpeedProfileSamples);
}

class SpectralArcLengthCHOP : public EwChop {
public:
    explicit SpectralArcLengthCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("spectral_arc_length")}; }

    void declareParameters(Params& p) override {
        p.page("Spectral Arc Length");
        p.number("Amplitudethreshold", "Amplitude Threshold", 0.05, Range::between(0.0, 1.0).withSlider(0.001, 0.5));
        p.number("Minimumcutofffrequency", "Minimum Cutoff Frequency (Hz)", 2.0, Range::atLeast(0.1, 20.0).withSlider(0.5, 20.0));
        p.number("Maximumcutofffrequency", "Maximum Cutoff Frequency (Hz)", 20.0, Range::atLeast(0.5, 50.0).withSlider(2.0, 50.0));
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

        ew::motion::SpectralArcLength::Params p;
        p.samplingRate = input.sampleRate();
        p.amplitudeThreshold = in->getParDouble("Amplitudethreshold");
        p.minimumCutoffFrequency = in->getParDouble("Minimumcutofffrequency");
        p.maximumCutoffFrequency = in->getParDouble("Maximumcutofffrequency");
        const double value = ew::motion::SpectralArcLength(p).process(speed);
        require(std::isfinite(value), "spectral_arc_length is NaN: the profile cannot support it");
        out->channels[0][0] = static_cast<float>(value);
    }
};

EW_TD_CHOP(SpectralArcLengthCHOP, "Ewspectralarclength", "EW L2 Spectral Arc Length", 1, 1)
