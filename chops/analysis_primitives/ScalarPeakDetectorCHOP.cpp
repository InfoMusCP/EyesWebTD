// TouchDesigner Scalar Peak Detector CHOP - wraps ew::dance::ScalarPeakDetector
// Input: exactly 1 channel time series. A NaN or infinite sample is skipped (INVALID_INPUT, output 0, not fed).
// Output: 1 channel (is_peak: 1 on the sample where a peak is found, else 0) per input sample; 0 and WARMING_UP
// while the buffer fills (the first Window - 1 samples).
// Streaming operator (see ew_td/stream_chop.h): Source = stream keeps the state between cooks, Source = clip starts
// afresh at every cook; Reset forgets the state.
#include "ew/features/dance/scalar_peak_detector.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"
#include "ew_td/stream_chop.h"

using namespace TD;
using namespace ew_td;
using ew::dance::ScalarPeakDetector;

class ScalarPeakDetectorCHOP : public EwStreamChop {
public:
    explicit ScalarPeakDetectorCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("is_peak")}; }

    void declareParameters(Params& p) override {
        p.page("Peak Detector");
        p.integer("Window", "Window (samples)", 5, Range::atLeast(2, 50));
        p.number("Threshold", "Threshold", 0.01, Range::atLeast(0.0, 1.0).withSlider(0.001, 1.0));
    }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        require(input.channels() == 1, "Requires 1 input channel");

        ScalarPeakDetector::Params p;
        p.window = in->getParInt("Window");
        if (p.window < 2) p.window = 2;
        p.threshold = in->getParDouble("Threshold");
        ScalarPeakDetector& feature = feature_.get(p);

        bool filling = false, skipped = false;
        for (int s = 0; s < out->numSamples; ++s) {
            if (skipNonFinite(input, s)) {
                skipped = true;
                continue;
            }
            const auto peak = feature.process(input.at(0, s));
            filling = !peak;
            out->channels[0][s] = peak && *peak ? 1.f : 0.f;
        }
        if (filling && !skipped) setStatus(Status::WarmingUp, "buffer filling");
    }

    void dropState() override { feature_.drop(); }

private:
    FeatureSlot<ScalarPeakDetector> feature_;
};

EW_TD_CHOP(ScalarPeakDetectorCHOP, "Ewscalarpeakdetector", "EW AP Scalar Peak Detector", 1, 1)
