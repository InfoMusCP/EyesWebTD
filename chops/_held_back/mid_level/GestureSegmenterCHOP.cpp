// TouchDesigner Gesture Segmenter CHOP - wraps ew::motion::GestureSegmenter
// Segments an intensity signal (for instance a kinetic energy) into gestures and measures the gestures and the pauses.
// Input: channel 0 = intensity.
// Output: 6 channels per input sample: smoothed_intensity, is_gesturing, is_gesture_start, is_gesture_end (0 while the
// window fills: the status is then WARMING_UP), motion_duration and pause_duration in seconds (NaN when not given: on the
// samples that end no phase unless Continuous Output is on, and until a phase of that kind has ended). Time is the sample
// rate of the input; a NaN or infinite sample is skipped (INVALID_INPUT) and its time counts in the running phase, as with
// timestamps in PyEyesWeb.
// Streaming operator (see ew_td/stream_chop.h): Source = stream keeps the state between cooks, Source = clip starts
// afresh at every cook; Reset forgets the state.
#include <limits>
#include "ew/features/motion/gesture_segmenter.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"
#include "ew_td/stream_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::GestureSegmenter;

class GestureSegmenterCHOP : public EwStreamChop {
public:
    explicit GestureSegmenterCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        return {Output::scalar("smoothed_intensity"), Output::scalar("is_gesturing"), Output::scalar("is_gesture_start"),
                Output::scalar("is_gesture_end"), Output::scalar("motion_duration"), Output::scalar("pause_duration")};
    }

    void declareParameters(Params& p) override {
        p.page("Gesture Segmenter");
        p.number("Firingthreshold", "Firing Threshold", 0.1, Range::atLeast(0.0, 2.0).withSlider(0.001, 2.0));
        p.integer("Filterwindowlength", "Filter Window Length (odd)", 9, Range::atLeast(5, 31));
        p.toggle("Continuousoutput", "Continuous Output", false);
    }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        require(input.channels() >= 1, "Requires at least 1 channel (intensity)");

        GestureSegmenter::Params p;
        p.firingThreshold = in->getParDouble("Firingthreshold");
        p.filterWindowLength = in->getParInt("Filterwindowlength");
        p.continuousOutput = in->getParInt("Continuousoutput") != 0;
        require(p.filterWindowLength >= 5 && p.filterWindowLength % 2 == 1,
                "Filter Window Length must be odd and at least 5");
        GestureSegmenter& segmenter = segmenter_.get(p);

        constexpr float kNaN = std::numeric_limits<float>::quiet_NaN();
        bool filling = false;
        bool skipped = false;
        for (int s = 0; s < out->numSamples; ++s) {
            for (int c = 4; c < 6; ++c) out->channels[c][s] = kNaN;
            if (!started_) {
                started_ = true;  // the first sample has no previous one: one sample period, as in PyEyesWeb
            } else {
                pending_ += input.dt();
            }
            if (skipNonFinite(input, s)) {
                skipped = true;
                continue;
            }
            const auto res = segmenter.process(input.at(0, s), pending_ > 0 ? pending_ : input.dt());
            pending_ = 0;
            filling = !res;
            if (!res) continue;
            out->channels[0][s] = static_cast<float>(res->smoothedIntensity);
            out->channels[1][s] = res->gesturing ? 1.f : 0.f;
            out->channels[2][s] = res->gestureStart ? 1.f : 0.f;
            out->channels[3][s] = res->gestureEnd ? 1.f : 0.f;
            if (res->motionDuration) out->channels[4][s] = static_cast<float>(*res->motionDuration);
            if (res->pauseDuration) out->channels[5][s] = static_cast<float>(*res->pauseDuration);
        }
        if (filling && !skipped) setStatus(Status::WarmingUp, "window filling");
    }

    void dropState() override {
        segmenter_.drop();
        started_ = false;
        pending_ = 0;
    }

private:
    FeatureSlot<GestureSegmenter> segmenter_;
    bool started_ = false;
    double pending_ = 0;  // time since the last sample given to the segmenter
};

EW_TD_CHOP(GestureSegmenterCHOP, "Ewgesturesegmenter", "EW L3 Gesture Segmenter", 1, 1)
