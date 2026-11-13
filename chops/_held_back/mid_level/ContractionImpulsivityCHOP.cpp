// TouchDesigner Contraction Impulsivity CHOP - wraps ew::motion::ImpulsivityIndex
// Input: 2 channels: quantity of motion (segmented, in [0, 1]) and contraction index (in [0, 1])
// Output: 2 channels per input sample: impulsivity_index and gesture_duration (gesture length in frames)
// Streaming operator (see ew_td/stream_chop.h): Source = stream keeps the state between cooks, Source = clip starts
// afresh at every cook; Reset forgets the state.
#include "ew/features/motion/impulsivity_index.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"
#include "ew_td/stream_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::ImpulsivityIndex;

class ContractionImpulsivityCHOP : public EwStreamChop {
public:
    explicit ContractionImpulsivityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        return {Output::scalar("impulsivity_index"), Output::scalar("gesture_duration")};
    }

    void declareParameters(Params& p) override {
        p.page("Impulsivity");
        p.number("Gesdur", "Max Gesture Duration (frames)", 25.0, Range::atLeast(1, 300));
        p.number("Threshold", "Peak Sqom Threshold", 0.02, Range::between(0.0, 1.0));
        p.number("Frames", "Frame Rate (fps)", 60.0, Range::atLeast(1, 240));
    }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        require(input.channels() >= 2, "Impulsivity requires at least 2 channels: quantity of motion and contraction index");

        ImpulsivityIndex::Params p;
        p.gestureDuration = in->getParDouble("Gesdur");
        p.peakThreshold = in->getParDouble("Threshold");
        p.samplingRate = in->getParDouble("Frames");
        if (p.samplingRate <= 0) p.samplingRate = input.sampleRate();
        ImpulsivityIndex& feature = feature_.get(p);

        for (int s = 0; s < out->numSamples; ++s) {
            if (skipNonFinite(input, s)) continue;
            const auto res = feature.process(input.at(0, s), input.at(1, s));
            out->channels[0][s] = static_cast<float>(res.ii);
            out->channels[1][s] = static_cast<float>(res.maxtime);
        }
    }

    void dropState() override { feature_.drop(); }

private:
    FeatureSlot<ImpulsivityIndex> feature_;
};

EW_TD_CHOP(ContractionImpulsivityCHOP, "Ewcontractionimpulsivity", "EW L3 Contraction Impulsivity", 1, 1)
